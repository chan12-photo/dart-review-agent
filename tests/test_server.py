"""The local API (dart_review.server): jobs, their log, and the HTTP round trip on a real local server.

The extraction runs inline (no worker thread) on a sample text PDF with the rules reader, so no model is needed.
The HTTP test starts uvicorn on a free 127.0.0.1 port and talks to it with urllib (no extra test package).
"""

from concurrent.futures import Executor, Future
from importlib.util import find_spec
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.documents.samples import SampleStatement, text_pdf  # noqa: E402
from dart_review.server import JobStore, UploadError, Worker  # noqa: E402

HAS_DOCS = all(find_spec(name) is not None for name in ("pdfplumber", "pypdfium2", "openpyxl"))
HAS_SERVER = HAS_DOCS and all(find_spec(name) is not None for name in ("fastapi", "uvicorn", "multipart"))

SAMPLE = SampleStatement(
    "재무상태표", "주식회사 예시", ["제 57 기 2025년 12월 31일 현재", "제 56 기 2024년 12월 31일 현재"], "백만원",
    ["제 57 (당) 기", "제 56 (전) 기"],
    [("유동자산", ["247,684,612", "227,062,266"]), ("비유동자산", ["319,257,498", "287,469,682"]),
     ("자산총계", ["566,942,110", "514,531,948"]), ("부채총계", ["130,621,773", "112,339,878"]),
     ("자본총계", ["436,320,337", "402,192,070"])])


class Inline(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def sample_pdf_bytes() -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "sample.pdf"
        text_pdf(path, [SAMPLE])
        return path.read_bytes()


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.folder.name))

    def tearDown(self):
        self.folder.cleanup()

    def test_only_pdfs_are_accepted(self):
        for data, reader, message in ((b"", "ai", "빈 파일"), (b"hello", "ai", "PDF 파일만"),
                                      (b"%PDF-1.4", "gpt", "reader는")):
            with self.assertRaisesRegex(UploadError, message):
                self.store.create("a.pdf", data, reader, None)

    def test_a_job_is_logged_with_its_input(self):
        job = self.store.create("../../보고서.pdf", b"%PDF-1.4 test", "rules", [10, 11])
        self.assertEqual((job["status"], job["filename"], job["pages"], job["size"]), ("queued", "보고서.pdf", "10,11", 13))
        self.assertEqual(len(job["sha256"]), 64)
        self.assertTrue((Path(self.folder.name) / job["id"] / "source.pdf").exists())

    def test_ids_that_are_not_job_ids_never_reach_the_file_system(self):
        for job_id in ("../jobs.sqlite3", "..", uuid.uuid4().hex.upper(), "x" * 32):
            with self.assertRaises(KeyError):
                self.store.get(job_id)

    def test_a_finished_job_can_be_deleted_with_its_files(self):
        job = self.store.create("a.pdf", b"%PDF-1.4 test", "rules", None)
        with self.assertRaises(UploadError):
            self.store.delete(job["id"])  # still queued
        self.store.update(job["id"], status="failed")
        self.store.delete(job["id"])
        self.assertFalse((Path(self.folder.name) / job["id"]).exists())
        with self.assertRaises(KeyError):
            self.store.get(job["id"])


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.store = JobStore(Path(self.folder.name))

    def tearDown(self):
        self.folder.cleanup()

    @unittest.skipUnless(HAS_DOCS, "pip install -e '.[docs]'")
    def test_a_job_writes_the_workbook_and_the_report(self):
        job = self.store.create("sample.pdf", sample_pdf_bytes(), "rules", None)
        Worker(self.store, executor=Inline()).submit(job["id"])
        done = self.store.get(job["id"])
        self.assertEqual((done["status"], done["statements"], done["cells"], done["flagged"]), ("done", 1, 10, 0))
        folder = Path(self.folder.name) / job["id"]
        self.assertTrue((folder / "result.xlsx").read_bytes().startswith(b"PK"))
        report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
        first = report["statements"][0]["rows"][0]
        self.assertEqual((first["label"], first["values"][0]["value"], first["values"][0]["status"]),
                         ("유동자산", 247_684_612_000_000, "검사 통과"))

    def test_a_failed_job_keeps_the_service_up_and_says_why(self):
        def broken(source, workbook, reader, pages):
            raise ValueError("secret document text")

        job = self.store.create("a.pdf", b"%PDF-1.4 test", "rules", None)
        Worker(self.store, runner=broken, executor=Inline()).submit(job["id"])
        failed = self.store.get(job["id"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["error"], "읽는 중 오류가 났습니다 (ValueError)")  # never the exception's text


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def multipart(fields: dict[str, str], filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields.items()]
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                 f"Content-Type: application/pdf\r\n\r\n".encode() + data + b"\r\n")
    return b"".join(parts) + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


@unittest.skipUnless(HAS_SERVER, "pip install -e '.[docs,server]'")
class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import uvicorn
        from dart_review.server import create_app
        cls.folder = tempfile.TemporaryDirectory()
        cls.port = free_port()
        app = create_app(Path(cls.folder.name), executor=Inline())
        cls.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=cls.port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < deadline:
            time.sleep(0.05)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=10)
        cls.folder.cleanup()

    def call(self, method, path, body=None, content_type=None):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers.get("Content-Type", ""), error.read()

    def test_upload_read_download_delete(self):
        status, kind, page = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("검증된 엑셀", page.decode())

        body, content_type = multipart({"reader": "rules", "pages": ""}, "sample.pdf", sample_pdf_bytes())
        status, _, raw = self.call("POST", "/jobs", body, content_type)
        self.assertEqual(status, 202)
        job_id = json.loads(raw)["id"]

        status, _, raw = self.call("GET", f"/jobs/{job_id}")
        job = json.loads(raw)
        self.assertEqual((job["status"], job["cells"], job["flagged"]), ("done", 10, 0))

        status, kind, workbook = self.call("GET", job["links"]["workbook"])
        self.assertEqual((status, workbook[:2]), (200, b"PK"))
        self.assertIn("spreadsheetml", kind)
        status, _, raw = self.call("GET", job["links"]["report"])
        self.assertEqual(json.loads(raw)["statements"][0]["unit"], "백만원")

        self.assertEqual(self.call("DELETE", f"/jobs/{job_id}")[0], 204)
        self.assertEqual(self.call("GET", f"/jobs/{job_id}")[0], 404)

    def test_a_file_that_is_not_a_pdf_is_refused(self):
        body, content_type = multipart({"reader": "rules"}, "note.txt", b"just text")
        status, _, raw = self.call("POST", "/jobs", body, content_type)
        self.assertEqual((status, json.loads(raw)["detail"]), (400, "PDF 파일만 받습니다"))

    def test_bad_page_numbers_and_unknown_jobs(self):
        body, content_type = multipart({"reader": "rules", "pages": "열"}, "a.pdf", b"%PDF-1.4")
        self.assertEqual(self.call("POST", "/jobs", body, content_type)[0], 400)
        self.assertEqual(self.call("GET", "/jobs/" + uuid.uuid4().hex)[0], 404)
        self.assertEqual(self.call("GET", "/jobs/..%2Fjobs.sqlite3")[0], 404)


if __name__ == "__main__":
    unittest.main()
