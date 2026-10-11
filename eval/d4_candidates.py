"""D4 candidate rules (contract 3.2): which filing and attachment of a candidate company, and whether its PDF is a
text PDF. They decide by fixed rules and record every input, so no person picks by what a document looks like.

    python eval/d4_candidates.py select --input candidate.json  # steps 1-4: what to download, or why not
    python eval/d4_candidates.py check --pdf candidate.pdf      # step 6: the mechanical PDF check, as JSON

``select`` takes one candidate's recorded inputs (its corp code, the 업종 code of company.json, the list.json
filings, the excluded corp codes fixed at step ④, and the attachment names as DART lists them for each filing
looked at) and gives the decision with every filing it considered:
- ``report_filings``: the 2025 사업보고서 filings of OpenDART's list.json (any prefix: [기재정정], [첨부정정],
  [첨부추가]), latest first by receipt date and number. The first of them whose attachments include a
  consolidated audit report is used (a later filing may add or correct attachments only).
- ``pick_attachment``: the first attachment, in the order DART lists them, whose name has "연결감사보고서" and not
  "내부회계" (the internal control report), both without spaces; it returns its position too (two attachments
  may share a name). None excludes the filing.
- A filing whose attachment list was not recorded stops the decision ("기록 부족"): it is never skipped.

``check_pdf``: "포함" when pdfplumber opens every page and the PDF has a text layer (at least 1,000 characters other
than spaces, and at least half of its pages with 100 or more); else "열리지 않음" or "글자 층 없음". It counts
characters only: it does not read the statements, so it cannot prefer an easy document. The threshold is of the
whole document, not of the statement pages: it keeps each page's count, so the statement pages' text layer is
reported after the gold is built (Codex fourth review 11).
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


def pick_attachment(names: list[str]) -> dict | None:
    """The consolidated audit report among a filing's attachments, in DART's order: its position (1 first) and
    name."""
    for position, name in enumerate(names, 1):
        compact = re.sub(r"\s+", "", name)
        if "연결감사보고서" in compact and "내부회계" not in compact:
            return {"position": position, "name": name}
    return None


FINANCE = ("64", "65", "66")


def select(candidate: dict) -> dict:
    """Steps 1-4 of contract 3.2 for one candidate, from its recorded inputs only."""
    record = {"corp_code": candidate["corp_code"], "corp_name": candidate.get("corp_name"), "considered": []}
    if candidate["corp_code"] in set(candidate["excluded_codes"]):
        return record | {"decision": "제외", "reason": "개발·봉인 회사"}
    induty = candidate.get("induty_code")
    if induty is None:
        return record | {"decision": "기록 부족", "reason": "업종코드(company.json) 없음"}
    if str(induty).startswith(FINANCE):
        return record | {"decision": "제외", "reason": f"금융업 (업종코드 {induty})"}
    filings = report_filings(candidate.get("filings", []))
    if not filings:
        return record | {"decision": "제외", "reason": "사업보고서 (2025.12) 없음"}
    attachments = candidate.get("attachments", {})
    for filing in filings:
        names = attachments.get(filing["rcept_no"])
        if names is None:
            return record | {"decision": "기록 부족", "reason": f"{filing['rcept_no']}의 첨부 목록이 기록되지 않았다"}
        chosen = pick_attachment(names)
        record["considered"].append({"rcept_no": filing["rcept_no"], "report_nm": filing.get("report_nm"),
                                     "rcept_dt": filing.get("rcept_dt"), "attachments": names, "chosen": chosen})
        if chosen:
            return record | {"decision": "받기", "rcept_no": filing["rcept_no"], "attachment": chosen}
    return record | {"decision": "제외", "reason": "연결감사보고서 첨부 없음"}


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
    record |= {"pages": len(chars), "chars": sum(chars), "text_pages": text_pages, "page_chars": chars}
    if not chars:
        return record | {"verdict": "열리지 않음", "error": "no pages"}
    if sum(chars) < MIN_CHARS or text_pages * 2 < len(chars):
        return record | {"verdict": "글자 층 없음"}
    return record | {"verdict": "포함"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    choose = commands.add_parser("select", help="steps 1-4 from one candidate's recorded inputs (JSON)")
    choose.add_argument("--input", type=Path, required=True)
    check = commands.add_parser("check", help="the mechanical PDF check of a downloaded candidate")
    check.add_argument("--pdf", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "select":
        print(json.dumps(select(json.loads(args.input.read_text(encoding="utf-8"))), ensure_ascii=False))
    else:
        print(json.dumps(check_pdf(args.pdf), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
