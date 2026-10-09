"""Scan files that would be published for local paths, contacts, and secrets.

Checks every file git would track (tracked plus untracked-but-not-ignored) and
exits non-zero when it finds something that should not reach a public
repository.  Run it before committing or pushing:

    python scripts/check_public_safety.py
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from pathlib import Path


TEXT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("absolute_home_path", re.compile(r"/Users/[A-Za-z0-9._-]+|/home/[A-Za-z0-9._-]+|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+")),
    ("macos_temp_path", re.compile(r"/var/folders/[A-Za-z0-9_+-]+/|/private/tmp/[A-Za-z0-9._-]+")),
    ("email_address", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    # not inside a longer letter-or-digit run, so hex digests such as SHA-256 values do not match
    ("korean_phone_number", re.compile(r"(?<![0-9A-Za-z])01[016789]-?[0-9]{3,4}-?[0-9]{4}(?![0-9A-Za-z])")),
    ("api_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36}|xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("private_key_block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("opendart_key_param", re.compile(r"crtfc_key=[0-9A-Fa-f]{8,}")),
]
ALLOWED_EMAILS = {"noreply@anthropic.com"}
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "users.noreply.github.com")

FORBIDDEN_FILE_PATTERNS = ["*api_key*", "*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*", "*.gguf", "*.log", "events.jsonl", "*.pem", "*.key", "*.p12", "*.pfx", ".DS_Store"]
# Excluded-file fixtures for the read-only Agent policy tests.  They must stay
# synthetic: each one has to contain the word SYNTHETIC.
SYNTHETIC_ENV_FIXTURES: set[str] = set()


def local_key_value() -> str | None:
    """The real OpenDART key, if the local key file exists. Used only for matching; never printed."""
    path = Path(os.environ.get("DART_API_KEY_FILE", "~/.config/opendart/api_key")).expanduser()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def candidate_files(root: Path) -> list[str]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True,
    ).stdout.decode("utf-8")
    return sorted({name for name in output.split("\0") if name})


def email_allowed(value: str) -> bool:
    lowered = value.casefold()
    return lowered in ALLOWED_EMAILS or lowered.endswith(ALLOWED_EMAIL_DOMAINS)


def scan_text(rel: str, text: str) -> list[dict[str, object]]:
    findings = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for kind, pattern in TEXT_PATTERNS:
            for match in pattern.finditer(line):
                value = match.group(0)
                if kind == "email_address" and email_allowed(value):
                    continue
                findings.append({"path": rel, "line": line_no, "kind": kind, "value": value})
    return findings


def scan_file(root: Path, rel: str) -> list[dict[str, object]]:
    path = root / rel
    name = Path(rel).name
    findings: list[dict[str, object]] = []
    if path.is_symlink():
        return findings
    if any(fnmatch.fnmatch(name.casefold(), pattern.casefold()) for pattern in FORBIDDEN_FILE_PATTERNS):
        findings.append({"path": rel, "line": 0, "kind": "forbidden_file_type", "value": name})
    if name.casefold() == ".env" or name.casefold().startswith(".env."):
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        if rel not in SYNTHETIC_ENV_FIXTURES or "SYNTHETIC" not in text:
            findings.append({"path": rel, "line": 0, "kind": "env_file", "value": name})
    try:
        raw = path.read_bytes()
    except OSError as exc:
        findings.append({"path": rel, "line": 0, "kind": "unreadable", "value": type(exc).__name__})
        return findings
    if b"\x00" in raw[:8192]:
        return findings
    findings.extend(scan_text(rel, raw.decode("utf-8", errors="replace")))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    findings = []
    files = candidate_files(args.root)
    secret = local_key_value()
    for rel in files:
        findings.extend(scan_file(args.root, rel))
        if secret and secret in (args.root / rel).read_bytes().decode("utf-8", errors="ignore"):
            findings.append({"path": rel, "line": 0, "kind": "opendart_key_value", "value": "<redacted>"})
    # Only the kind and the place: a matched value may itself be a secret or personal data,
    # and this output can end up in a public CI log.
    for item in findings:
        print(f"{item['path']}:{item['line']}: {item['kind']}")
    print(f"scanned {len(files)} files, {len(findings)} finding(s)", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
