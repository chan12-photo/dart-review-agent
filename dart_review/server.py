"""A local HTTP API for "document → checked workbook" (v0.2 D5), with a small upload page (D6).

    pip install -e '.[docs,server]'
    python -m dart_review serve            # http://127.0.0.1:8000

POST /jobs (a PDF) queues a job and returns its id at once; one worker reads the jobs in turn, because the
local vision model reads one band at a time anyway. GET /jobs/{id} gives the status and the counts,
GET /jobs/{id}/workbook the workbook, GET /jobs/{id}/report the checked values as JSON, and DELETE removes
the job's files. Every job is logged in SQLite (file name, size, SHA-256, reader, model, times, counts, error)
so a result can be traced to its input.

It is meant for one person on their own machine: it listens on 127.0.0.1 and has no accounts. Uploaded
documents stay in the data folder until their job is deleted. Jobs left unfinished when the server stops are
marked failed when it starts again (they are not run again); their files stay until deleted.
"""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from typing import Any, Callable, Iterator
import uuid

try:  # optional: pip install -e '.[server]'; the job store and worker work without it
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
except ImportError:  # pragma: no cover
    FastAPI = None

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
DEFAULT_DATA_DIR = Path.home() / ".dart_review" / "server"
READERS = ("ai", "rules")
_SCHEMA = """
create table if not exists jobs (
    id text primary key,
    created_at text not null,
    filename text not null,
    size integer not null,
    sha256 text not null,
    reader text not null,
    pages text,
    status text not null,           -- queued, running, done, failed
    started_at text,
    finished_at text,
    statements integer,
    cells integer,
    flagged integer,
    model text,
    model_calls integer,
    error text
)
"""


class UploadError(ValueError):
    """The upload is not a document this service reads; the message is shown to the user."""


class DeleteError(RuntimeError):
    """A job's files could not be removed; the message is shown to the user."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class JobStore:
    """Jobs in SQLite and their files in ``root/<id>/`` (source.pdf, result.xlsx, report.json)."""

    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.root / "jobs.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            with db:  # commits, or rolls back on an error
                yield db
        finally:
            db.close()

    def folder(self, job_id: str) -> Path:
        if not (len(job_id) == 32 and all(ch in "0123456789abcdef" for ch in job_id)):
            raise KeyError(job_id)  # ids are uuid4 hex; anything else never reaches the file system
        return self.root / job_id

    def create(self, filename: str, data: bytes, reader: str, pages: list[int] | None) -> dict[str, Any]:
        if reader not in READERS:
            raise UploadError(f"reader는 {', '.join(READERS)} 중 하나여야 합니다")
        if not data:
            raise UploadError("빈 파일입니다")
        if len(data) > MAX_UPLOAD_BYTES:
            raise UploadError(f"파일이 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB보다 큽니다")
        if not data.startswith(b"%PDF-"):
            raise UploadError("PDF 파일만 받습니다")
        job_id = uuid.uuid4().hex
        folder = self.folder(job_id)
        folder.mkdir()
        (folder / "source.pdf").write_bytes(data)
        row = {"id": job_id, "created_at": _now(), "filename": Path(filename or "document.pdf").name[:200],
               "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "reader": reader,
               "pages": ",".join(str(page) for page in pages) if pages else None, "status": "queued"}
        with self._lock, self._connect() as db:
            db.execute(f"insert into jobs ({', '.join(row)}) values ({', '.join('?' for _ in row)})", list(row.values()))
        return self.get(job_id)

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock, self._connect() as db:
            db.execute(f"update jobs set {', '.join(f'{name} = ?' for name in fields)} where id = ?",
                       [*fields.values(), job_id])

    def get(self, job_id: str) -> dict[str, Any]:
        self.folder(job_id)
        with self._connect() as db:
            row = db.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return dict(row)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute("select * from jobs order by created_at desc limit ?", (limit,))]

    def transition(self, job_id: str, from_states: tuple[str, ...], to_state: str, **fields: Any) -> bool:
        """Move a job to ``to_state`` only if it is in one of ``from_states``, in one statement; whether it moved.
        The worker starting a job and a request deleting it go through this, so they cannot both win."""
        assignments = {"status": to_state, **fields}
        with self._lock, self._connect() as db:
            cursor = db.execute(f"update jobs set {', '.join(f'{name} = ?' for name in assignments)} "
                                f"where id = ? and status in ({', '.join('?' for _ in from_states)})",
                                [*assignments.values(), job_id, *from_states])
            return cursor.rowcount == 1

    def delete(self, job_id: str) -> None:
        """Remove a finished job's files, then its record. A job being read cannot be deleted. If the files cannot
        be removed, the record stays (status delete_failed) so the deletion can be retried and is not lost."""
        self.get(job_id)
        if not self.transition(job_id, ("done", "failed", "delete_failed"), "deleting"):
            raise UploadError("읽는 중인 작업은 지울 수 없습니다")
        folder = self.folder(job_id)
        try:
            shutil.rmtree(folder)
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.update(job_id, status="delete_failed", error=f"파일을 지우지 못했습니다 ({type(exc).__name__})")
            raise DeleteError("파일을 지우지 못했습니다. 다시 시도하세요") from None
        if folder.exists():
            self.update(job_id, status="delete_failed", error="파일을 지우지 못했습니다")
            raise DeleteError("파일을 지우지 못했습니다. 다시 시도하세요")
        with self._lock, self._connect() as db:
            db.execute("delete from jobs where id = ?", (job_id,))

    def abandon_unfinished(self) -> int:
        """Jobs left queued or running by a previous server process are not run again: they are marked failed (their
        files stay until deleted). Called when the server starts."""
        with self._lock, self._connect() as db:
            cursor = db.execute("update jobs set status = 'failed', finished_at = ?, error = ? "
                                "where status in ('queued', 'running', 'deleting')",
                                (_now(), "서버가 다시 시작되어 읽기가 끝나지 않았습니다. 다시 올려 주세요"))
            return cursor.rowcount


def report(extraction, source_name: str, reader: str) -> dict[str, Any]:
    """The checked values as JSON: per statement, every value with its printed text, page, status, and reasons."""
    from .documents.excel import KINDS
    checks = {(c.statement, c.row, c.column): c for c in extraction.checks}
    statements = []
    for s_index, statement in enumerate(extraction.statements):
        rows = []
        for r_index, row in enumerate(statement.rows):
            values = []
            for c_index, amount in sorted(row.amounts.items()):
                check = checks.get((s_index, r_index, c_index))
                values.append({"column": c_index, "value": amount.value, "printed": amount.printed,
                               "page": amount.cell.page, "status": check.status if check else None,
                               "reasons": check.reasons if check else [], "evidence": check.evidence if check else ""})
            rows.append({"label": row.label, "account": row.account, "values": values})
        statements.append({"title": statement.title, "kind": KINDS.get(statement.kind, statement.kind),
                           "page": statement.page, "unit": statement.unit_text,
                           "columns": [{"header": c.header, "year": c.year, "end": c.end} for c in statement.columns],
                           "rows": rows, "problems": statement.problems, "sums_checked": statement.sums_checked})
    return {"source": source_name, "reader": reader, "cells": len(extraction.checks),
            "needs_review": extraction.needs_review, "statements": statements, "problems": extraction.problems}


Runner = Callable[[Path, Path, str, "list[int] | None"], Any]


def run_extraction(source: Path, workbook: Path, reader: str, pages: list[int] | None):
    from .documents import extract
    return extract(source, workbook, reader=reader, pages=pages)


class Worker:
    """Runs queued jobs one at a time. ``runner`` is the extraction (replaced in tests)."""

    def __init__(self, store: JobStore, runner: Runner = run_extraction, executor: Executor | None = None):
        self.store, self.runner = store, runner
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="dart-review-job")

    def submit(self, job_id: str) -> None:
        self.executor.submit(self.run, job_id)

    def run(self, job_id: str) -> None:
        if not self.store.transition(job_id, ("queued",), "running", started_at=_now()):
            return  # deleted or abandoned before its turn
        job = self.store.get(job_id)
        folder = self.store.folder(job_id)
        pages = [int(page) for page in job["pages"].split(",")] if job["pages"] else None
        try:
            extraction = self.runner(folder / "source.pdf", folder / "result.xlsx", job["reader"], pages)
            data = report(extraction, job["filename"], job["reader"])
            (folder / "report.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            self.store.update(job_id, status="done", finished_at=_now(), statements=len(extraction.statements),
                              cells=len(extraction.checks), flagged=extraction.needs_review,
                              model=getattr(extraction, "model", None), model_calls=getattr(extraction, "model_calls", None))
        except Exception as exc:  # the job fails, the service stays up; the message never holds document text
            self.store.update(job_id, status="failed", finished_at=_now(), error=_error_message(exc))


# the messages this package raises, by shape; only these are shown as they are (they hold no document text).
# Anything else, a library's RuntimeError included, is shown as a fixed message with the exception's class name.
_SAFE_MESSAGES = tuple(re.compile(pattern) for pattern in (
    r"no text was found \(the scan may be empty or unreadable\)",
    r"cannot read the PDF: \w+",
    r"tesseract failed with exit code -?\d+",
    r"(pdfplumber|pypdfium2|openpyxl) is not installed: pip install -e '\.\[docs\]'",
    r"tesseract is not installed \(brew install tesseract tesseract-lang\)",
    r"could not reach the local vision model \(\w+\); is Ollama running\?",
    r"the model ran out of its output budget on one band",
))


def _error_message(exc: Exception) -> str:
    from .documents.vision import VisionError
    from .documents.words import DocumentError
    text = str(exc)
    if isinstance(exc, (DocumentError, VisionError, RuntimeError)) and any(p.fullmatch(text) for p in _SAFE_MESSAGES):
        return text
    return f"읽는 중 오류가 났습니다 ({type(exc).__name__})"


def _lock_data_dir(root: Path):
    """An exclusive lock on the data folder for the life of the server. A second server on the same folder would
    take the first one's running jobs for abandoned ones and mark them failed; it refuses to start instead."""
    handle = open(root / "server.lock", "a+")
    try:
        import fcntl
    except ImportError:  # pragma: no cover - Windows: no lock, one server per folder is the user's rule
        return handle
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("다른 서버가 이 데이터 폴더를 쓰고 있습니다 (--data로 다른 폴더를 주세요)") from None
    return handle


def _public(job: dict[str, Any]) -> dict[str, Any]:
    links = {}
    if job["status"] == "done":
        links = {"workbook": f"/jobs/{job['id']}/workbook", "report": f"/jobs/{job['id']}/report"}
    return {**job, "links": links}


def create_app(data_dir: Path = DEFAULT_DATA_DIR, runner: Runner = run_extraction, executor: Executor | None = None):
    if FastAPI is None:
        raise RuntimeError("fastapi is not installed: pip install -e '.[docs,server]'")

    store = JobStore(Path(data_dir))
    lock = _lock_data_dir(store.root)
    store.abandon_unfinished()  # safe: no other server uses this folder while the lock is held
    worker = Worker(store, runner, executor)
    app = FastAPI(title="dart-review documents", version="0.2.0-dev",
                  description="PDF 재무제표 → 검증된 엑셀 (로컬 전용)")
    app.state.store, app.state.worker, app.state.lock = store, worker, lock

    def job_or_404(job_id: str) -> dict[str, Any]:
        try:
            return store.get(job_id)
        except KeyError:
            raise HTTPException(404, "작업을 찾지 못했습니다") from None

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return (Path(__file__).parent / "upload.html").read_text(encoding="utf-8")

    @app.get("/health")
    def health() -> dict[str, Any]:
        from .documents.vision import ollama_ready
        return {"status": "ok", "ai_reader": ollama_ready()}

    @app.post("/jobs", status_code=202)
    async def create_job(file: UploadFile = File(...), reader: str = Form("ai"), pages: str = Form("")):
        data = await file.read(MAX_UPLOAD_BYTES + 1)
        try:
            page_list = [int(page) for page in pages.replace(" ", "").split(",") if page] or None
        except ValueError:
            raise HTTPException(400, "쪽 번호는 '10,11'처럼 적습니다") from None
        try:
            job = store.create(file.filename or "document.pdf", data, reader, page_list)
        except UploadError as exc:
            raise HTTPException(400, str(exc)) from None
        worker.submit(job["id"])
        return _public(job)

    @app.get("/jobs")
    def list_jobs() -> list[dict[str, Any]]:
        return [_public(job) for job in store.list()]

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _public(job_or_404(job_id))

    @app.get("/jobs/{job_id}/workbook")
    def workbook(job_id: str):
        job = job_or_404(job_id)
        path = store.folder(job_id) / "result.xlsx"
        if job["status"] != "done" or not path.exists():
            raise HTTPException(409, "아직 엑셀이 없습니다")
        name = Path(job["filename"]).stem + ".xlsx"
        return FileResponse(path, filename=name,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.get("/jobs/{job_id}/report")
    def job_report(job_id: str):
        job = job_or_404(job_id)
        path = store.folder(job_id) / "report.json"
        if job["status"] != "done" or not path.exists():
            raise HTTPException(409, "아직 결과가 없습니다")
        return JSONResponse(json.loads(path.read_text(encoding="utf-8")))

    @app.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str) -> None:
        job_or_404(job_id)
        try:
            store.delete(job_id)
        except UploadError as exc:
            raise HTTPException(409, str(exc)) from None
        except DeleteError as exc:
            raise HTTPException(500, str(exc)) from None

    return app
