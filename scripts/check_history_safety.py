"""Scan the whole git history before publishing: every file version ever committed, and every commit message.

check_public_safety.py looks at the files as they are now; a secret removed
later would still be in an older commit. This applies the same patterns, plus
the local OpenDART key value (read only to match, never printed), to every blob
reachable from any ref, to every path that ever existed, and to commit messages.

    python scripts/check_history_safety.py
"""

from __future__ import annotations

import argparse
import fnmatch
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_public_safety import FORBIDDEN_FILE_PATTERNS, local_key_value, scan_text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args(argv).root

    def git(*args: str) -> bytes:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout

    key = local_key_value()
    objects = git("rev-list", "--objects", "--all").decode("utf-8").splitlines()
    paths: dict[str, set[str]] = {}
    for line in objects:
        sha, _, path = line.partition(" ")
        if path:
            paths.setdefault(sha, set()).add(path)
    findings = []
    for path in sorted({path for names in paths.values() for path in names}):
        if any(fnmatch.fnmatch(Path(path).name.casefold(), pattern.casefold()) for pattern in FORBIDDEN_FILE_PATTERNS):
            findings.append(("path", path, "forbidden_file_type"))
    blobs = [sha for sha in paths if git("cat-file", "-t", sha).strip() == b"blob"]
    for sha in blobs:
        raw = git("cat-file", "blob", sha)
        if b"\x00" in raw[:8192]:
            continue
        text = raw.decode("utf-8", errors="replace")
        where = sorted(paths[sha])[0]
        if key and key in text:
            findings.append(("blob", where, "opendart_key_value"))
        findings += [("blob", f"{where}:{item['line']}", item["kind"]) for item in scan_text(where, text)]
    messages = git("log", "--all", "--format=%H%x00%B%x01").decode("utf-8").split("\x01")
    for entry in messages:
        commit, _, body = entry.strip().partition("\x00")
        if not commit:
            continue
        if key and key in body:
            findings.append(("message", commit[:7], "opendart_key_value"))
        findings += [("message", f"{commit[:7]}:{item['line']}", item["kind"]) for item in scan_text(commit[:7], body)]
    print(f"scanned {len(blobs)} file versions, {len(paths)} objects, {len([m for m in messages if m.strip()])} commit messages; "
          f"key value check {'on' if key else 'OFF (no local key file)'}; {len(findings)} finding(s)")
    # Only the kind and the place, never the matched value (see check_public_safety.py).
    for where, name, kind in findings:
        print(f"  {where} {name}: {kind}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
