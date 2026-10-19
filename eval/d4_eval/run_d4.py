"""D4 official run (contract 1.2 step ⑧ and 7): every document through eval/d4_score.py, in the registered order.

    python eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out <run folder> --dry-run
    python eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out <run folder>

Order: the rules reader first, then the AI reader (contract ⑧); within a reader, each document of
eval/d4_eval/documents.json in order, its text PDF and then its synthetic scans (normal, tilt, blur). Each run is
one call of the frozen scorer with --pdf: the product reads the file once, its report is saved once (never
overwritten), and the machine score is written next to it. Every input file's SHA-256 is checked against the
document list before anything runs, so no other bytes can be read. Each call's start, end, exit code, and the last
lines of its output go to ``run_log.jsonl``; a failure is recorded and the run goes on (contract 7: after a model
server failure the whole reader is run again in a new folder, and both folders are kept). The run folder must not
exist. ``--dry-run`` checks the inputs and prints the commands without running anything.

The official run happens in a checkout of the registered commit R after ``eval/d4_preflight.py check`` passes
(contract 1.2); this script does not repeat that check, it records the commit it ran at.
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--scan-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--readers", nargs="+", choices=READERS, default=list(READERS),
                        help="only for re-running one reader in a new folder after a model server failure")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"{args.out} exists: a run folder is never reused")
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
    (args.out / "reports").mkdir(parents=True)
    (args.out / "scores").mkdir()
    run = {"started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "commit": _git("rev-parse", "HEAD"),
           "status_porcelain": _git("status", "--porcelain", "--untracked-files=all"), "python": platform.python_version(),
           "documents_sha256": _sha256(DOCUMENTS), "readers": args.readers, "calls": len(calls),
           "argv": sys.argv[1:]}
    (args.out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
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
    finished = {**run, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (args.out / "run.json").write_text(json.dumps(finished, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
