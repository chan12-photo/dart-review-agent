"""D4 candidate rules (contract 3.2): which filing and attachment of a candidate company, and whether its PDF is a
text PDF. They decide by fixed rules and record every input, so no person picks by what a document looks like.

    python eval/d4_candidates.py check --pdf candidate.pdf     # the mechanical PDF check, as JSON

- ``report_filings``: the 2025 사업보고서 filings of OpenDART's list.json (any prefix: [기재정정], [첨부정정],
  [첨부추가]), latest first by receipt date and number. The first of them whose attachments include a
  consolidated audit report is used (a later filing may add or correct attachments only).
- ``pick_attachment``: the first attachment, in the order DART lists them, whose name has "연결감사보고서" and not
  "내부회계" (the internal control report); None excludes the filing.
- ``check_pdf``: "포함" when pdfplumber opens every page and the PDF has a text layer (at least 1,000 characters
  other than spaces, and at least half of its pages with 100 or more); else "열리지 않음" or "글자 층 없음". It
  counts characters only: it does not read the statements, so it cannot prefer an easy document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

REPORT = re.compile(r"^(?:\[[^\]]+\]\s*)*사업보고서\s*\(2025\.12\)$")
MIN_CHARS, MIN_PAGE_CHARS = 1_000, 100


def report_filings(filings: list[dict]) -> list[dict]:
    """The 2025 사업보고서 filings, latest first (receipt date, then receipt number)."""
    found = [f for f in filings if REPORT.match(re.sub(r"\s+", " ", f.get("report_nm", "")).strip())]
    return sorted(found, key=lambda f: (f.get("rcept_dt", ""), f.get("rcept_no", "")), reverse=True)


def pick_attachment(names: list[str]) -> str | None:
    """The consolidated audit report among a filing's attachments, in DART's order."""
    return next((name for name in names if "연결감사보고서" in name.replace(" ", "") and "내부회계" not in name), None)


def check_pdf(path: Path) -> dict:
    data = path.read_bytes()
    record = {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            chars = [len(re.sub(r"\s+", "", page.extract_text() or "")) for page in pdf.pages]
    except Exception as exc:  # any failure to open or read a page: the rule does not look further
        return record | {"verdict": "열리지 않음", "error": f"{type(exc).__name__}: {exc}"[:300]}
    text_pages = sum(n >= MIN_PAGE_CHARS for n in chars)
    record |= {"pages": len(chars), "chars": sum(chars), "text_pages": text_pages}
    if not chars:
        return record | {"verdict": "열리지 않음", "error": "no pages"}
    if sum(chars) < MIN_CHARS or text_pages * 2 < len(chars):
        return record | {"verdict": "글자 층 없음"}
    return record | {"verdict": "포함"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="the mechanical PDF check of a downloaded candidate")
    check.add_argument("--pdf", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check_pdf(args.pdf), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
