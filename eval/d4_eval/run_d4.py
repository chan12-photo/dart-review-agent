"""D4 official run (contract 1.2 step ⑧ and 7): every document through eval/d4_score.py, in the registered order.

    python eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out <run folder> --dry-run
    python eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out <run folder> \
        --preflight <run folder>.preflight.json

Order: the rules reader first, then the AI reader (contract ⑧); within a reader, each document of
eval/d4_eval/documents.json in order, its text PDF and then its synthetic scans (normal, tilt, blur). Each run is
one call of the frozen scorer with --pdf: the product reads the file once, its report is saved once (never
overwritten), and the machine score is written next to it. Every input file's SHA-256 is checked against the
document list before anything runs, so no other bytes can be read. Each call's start, end, exit code, and the last
lines of its output go to ``run_log.jsonl``; a failure is recorded and the run goes on (contract 7: after a model
server failure the whole reader is run again in a new folder, and both folders are kept). ``run.json`` ends with
the calls that failed (exit code not 0) and the run exits 1 when any did, 0 only when every call exited 0 (Codex
seventh review 2; a score's ``official_ready`` is another matter, decided at ⑨).

The official run happens in a checkout of the registered commit R after ``eval/d4_preflight.py check`` passes
(contract 1.2). Its log is written next to the run folder, outside the checkout (``<run folder>.preflight.json``:
a log inside the run folder would make the folder exist, and one inside the checkout would make it unclean; Codex
seventh review 3). Before anything runs, this script requires: the run folder does not exist and is outside the
checkout, the preflight log is outside the checkout and says every check passed at this HEAD, and the checkout is
still clean (``git status --porcelain``). It records the log's SHA-256 with the commit. ``--dry-run`` checks the
inputs and prints the commands without running anything (no preflight log needed).
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ROOT / "eval" / "d4_eval" / "documents.json"
READERS = ("rules", "ai")
CONDITIONS = ("normal", "tilt", "blur")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def plan(documents: dict, pdf_dir: Path, scan_dir: Path, out: Path, readers=READERS) -> list[dict]:
    """The calls in order, after checking every input file's bytes. Raises ValueError on any mismatch."""
    calls = []
    for reader in readers:
        for document in documents["documents"]:
            variants = [("text", pdf_dir / document["pdf"], document["sha256"], None)]
            variants += [(condition, scan_dir / document["scans"][condition]["pdf"], document["scans"][condition]["sha256"],
                          document["scans"][condition]["map"]) for condition in CONDITIONS]
            for variant, path, expected, page_map in variants:
                if not path.exists():
                    raise ValueError(f"{document['key']} {variant}: {path.name} is not in its folder")
                if _sha256(path) != expected:
                    raise ValueError(f"{document['key']} {variant}: {path.name} is not the registered file (SHA-256)")
                name = f"{document['key']}.{variant}.{reader}"
                command = [sys.executable, str(ROOT / "eval" / "d4_score.py"), "--pdf", str(path),
                           "--report", str(out / "reports" / f"{name}.json"), "--gold", str(ROOT / document["gold"]),
                           "--mapping", str(ROOT / document["mapping"]), "--reader", reader,
                           "--out", str(out / "scores" / f"{name}.json")]
                if page_map:
                    command[-2:-2] = ["--page-map", str(ROOT / page_map)]
                calls.append({"name": name, "key": document["key"], "variant": variant, "reader": reader,
                              "command": command})
    return calls


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def _inside_checkout(path: Path) -> bool:
    return path.expanduser().resolve().is_relative_to(ROOT.resolve())


def preflight_passed(path: Path | None, head: str) -> dict:
    """The preflight log's path, SHA-256, and time, when it is outside the checkout and every check passed at HEAD."""
    if path is None:
        raise ValueError("--preflight (the log of eval/d4_preflight.py check) is required for a run")
    if not path.exists():
        raise ValueError(f"{path} does not exist: run python -m eval.d4_preflight check --log {path} first (docs/D4_RUN_PROCEDURE.ko.md)")
    if _inside_checkout(path):
        raise ValueError(f"{path} is inside the checkout: the preflight log goes outside it")
    log = json.loads(path.read_text(encoding="utf-8"))
    if log.get("ok") is not True or not log.get("checks") or not all(c.get("ok") is True for c in log["checks"]):
        raise ValueError(f"{path}: the preflight did not pass")
    if log.get("head") != head:
        raise ValueError(f"{path}: the preflight checked {log.get('head')}, not HEAD {head}")
    return {"log": str(path), "sha256": _sha256(path), "checked_at": log.get("checked_at")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--scan-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--readers", nargs="+", choices=READERS, default=list(READERS),
                        help="only for re-running one reader in a new folder after a model server failure")
    parser.add_argument("--preflight", type=Path, help="the passed log of eval/d4_preflight.py check (not with --dry-run)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.readers != [r for r in READERS if r in args.readers]:
        parser.error(f"--readers {' '.join(args.readers)}: each reader once, rules before ai (contract ⑧)")
    if args.out.exists():
        parser.error(f"{args.out} exists: a run folder is never reused")
    if _inside_checkout(args.out):
        parser.error(f"{args.out} is inside the checkout: the run folder goes outside it")
    documents = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    try:
        calls = plan(documents, args.pdf_dir.expanduser(), args.scan_dir.expanduser(), args.out, tuple(args.readers))
    except ValueError as exc:
        print(f"inputs do not match the registered documents: {exc}")
        return 2
    if args.dry_run:
        for call in calls:
            print(call["name"], " ".join(call["command"][1:]))
        print(f"{len(calls)} calls; inputs match the registered documents; nothing was run")
        return 0
    head = _git("rev-parse", "HEAD")
    try:
        preflight = preflight_passed(args.preflight, head)
    except ValueError as exc:
        print(f"not run: {exc}")
        return 2
    status = _git("status", "--porcelain", "--untracked-files=all")
    if status:
        print(f"not run: the checkout changed after the preflight (git status --porcelain):\n{status}")
        return 2
    (args.out / "reports").mkdir(parents=True)
    (args.out / "scores").mkdir()
    run = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": head,
           "status_porcelain": status, "preflight": preflight, "python": platform.python_version(),
           "documents_sha256": _sha256(DOCUMENTS), "readers": args.readers, "calls": len(calls),
           "argv": sys.argv[1:] if argv is None else argv}
    (args.out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    failed = []
    with (args.out / "run_log.jsonl").open("a", encoding="utf-8") as log:
        for number, call in enumerate(calls, 1):
            started = time.monotonic()
            begun = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = subprocess.run(call["command"], cwd=ROOT, capture_output=True, text=True)
            entry = {"n": number, "name": call["name"], "started_at": begun,
                     "seconds": round(time.monotonic() - started, 1), "exit": result.returncode,
                     "stdout_tail": result.stdout.strip().splitlines()[-3:], "stderr_tail": result.stderr.strip().splitlines()[-5:]}
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
            print(f"[{number}/{len(calls)}] {call['name']}: exit {result.returncode}, {entry['seconds']}s", flush=True)
            if result.returncode != 0:
                failed.append({"name": call["name"], "exit": result.returncode})
    finished = {**run, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "succeeded": len(calls) - len(failed), "failed": failed}
    (args.out / "run.json").write_text(json.dumps(finished, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if failed:
        print(f"{len(failed)} of {len(calls)} calls failed: {', '.join(f['name'] for f in failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
