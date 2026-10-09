"""Measure the document reader on real audit reports against OpenDART (v0.2; a measurement, not an evaluation).

    python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out eval/documents_2026-10-10
    python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader ai   --out eval/documents_2026-10-10

The PDFs are public audit reports but are not committed; each is identified by its SHA-256 and page count.
OpenDART (fnlttSinglAcntAll, annual; CFS for 연결 statements, OFS for 별도) is read from the response cache
(--offline by default).

Each extracted cell is put in one class:
- dart_exact: OpenDART has the same account name and value in that period
- dart_value: OpenDART has the value under another name (or the same row is named differently)
- dart_sign: OpenDART has the value with the opposite sign (cash outflows are stored either way)
- wrong_period: OpenDART has the value (either sign) only in the other period: put under the wrong period
- unit_mismatch: OpenDART has the value only after a factor of 10^3, 10^6 or 10^8: read in the wrong unit
- pdf_only: OpenDART has no such value, but the PDF's text layer prints this value on the row's line
  (OpenDART presents some details differently from the printed statement); text PDFs only
- unconfirmed: none of these.
A wrong_period, unit_mismatch or unconfirmed cell that is not marked "확인 필요" is a candidate silent error and is listed
for a person to look at.
Values OpenDART has for a statement that are in no extracted cell (either sign) are listed as not extracted.
The workbook's own checks are reported next to this: how many cells it marked "확인 필요".
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402

# the four 2025 consolidated audit reports used during v0.2 development (files from the companies' DART filings)
DOCUMENTS = [
    {"company": "삼성전자", "corp_code": "00126380", "file": "2025_con_quarter04_all.pdf"},
    {"company": "NAVER", "corp_code": "00266961", "file": "연결감사보고서_FY2025.pdf"},
    {"company": "한화시스템", "corp_code": "00339391", "file": "한화시스템_연결감사보고서(2026.03.13).pdf"},
    {"company": "포스코", "corp_code": "01620971", "file": "POSCO_consolidated_FY25.pdf"},
    # a 영업보고서 with both separate (별도) and consolidated statements, numbered titles
    {"company": "LG에너지솔루션", "corp_code": "01515323", "file": "2025_LGES_Business_Report.pdf"},
    # phone photos of printed statements, as a PDF without a text layer (the AI reader's hard case)
    {"company": "삼성전자 (사진 PDF)", "corp_code": "00126380",
     "file": "%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90_%EC%97%B0%EA%B2%B0%EC%9E%AC%EB%AC%B4%EC%A0%9C%ED%91%9C_%ED%86%B5%ED%95%A9.pdf"},
]
YEAR, REPORT = 2025, "11011"  # consolidated statements are compared with CFS, separate (별도) ones with OFS
CLASSES = ("dart_exact", "dart_value", "dart_sign", "wrong_period", "unit_mismatch", "pdf_only", "unconfirmed")
SCALES = (10 ** 3, 10 ** 6, 10 ** 8)


def name_key(name: str) -> str:
    name = re.sub(r"\s+|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.|^\d+\.|\(주석[^)]*\)|[·ㆍ.,]", "", name)
    return re.sub(r"\([^)]*\)$", "", name)


def integer(text: str | None) -> int | None:
    text = (text or "").replace(",", "").strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


def dart_values(items: list[dict], kind: str) -> dict[int, dict[int, set[str]]]:
    """Period (0 current, 1 prior) -> value -> account names, for the statement kind (IS falls back to CIS)."""
    present = {item["sj_div"] for item in items}
    if kind not in present:
        kind = {"IS": "CIS", "CIS": "IS"}.get(kind, kind)
    values: dict[int, dict[int, set[str]]] = {0: {}, 1: {}}
    for item in items:
        if item["sj_div"] != kind:
            continue
        for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount")):
            value = integer(item.get(field))
            if value is not None:
                values[period].setdefault(value, set()).add(name_key(item["account_nm"]))
    return values


def printed_on_page(path: Path) -> dict[int, list[str]]:
    """The text layer's lines per page (to confirm a value OpenDART presents differently)."""
    from dart_review.documents.table import group_lines
    from dart_review.documents.words import text_layer_words
    lines: dict[int, list[str]] = {}
    for line in group_lines(text_layer_words(path)):
        lines.setdefault(line.page, []).append(re.sub(r"\s+", "", line.text))
    return lines


class OpenDart(dict):
    """CFS or OFS items, fetched from the cache only when a statement needs them."""

    def __init__(self, client: DartClient, corp_code: str):
        super().__init__()
        self.client, self.corp_code = client, corp_code

    def __missing__(self, division: str) -> list[dict]:
        self[division] = self.client.financial_statements(self.corp_code, YEAR, REPORT, division).json()["list"]
        return self[division]


def classify(extraction, items_by_division: dict[str, list[dict]], text_lines: dict[int, list[str]]) -> dict:
    flagged = {(c.statement, c.row, c.column) for c in extraction.checks if c.status == "확인 필요"}
    statements = []
    for s_index, statement in enumerate(extraction.statements):
        if statement.kind == "SCE":
            statements.append({"title": statement.title, "page": statement.page, "skipped": True,
                               "problems": statement.problems})
            continue
        division = "OFS" if statement.title.startswith("별도") else "CFS"
        values = dart_values(items_by_division[division], statement.kind)
        counts = {name: 0 for name in CLASSES}
        flagged_counts = {name: 0 for name in CLASSES}
        attention, ours = [], {0: set(), 1: set()}
        for r_index, row in enumerate(statement.rows):
            for column, amount in row.amounts.items():
                if amount.value is None or column > 1:
                    continue
                ours[column].add(amount.value)
                key = name_key(row.label)
                if amount.value in values[column] and key in values[column][amount.value]:
                    kind = "dart_exact"
                elif amount.value in values[column]:
                    kind = "dart_value"
                elif -amount.value in values[column]:
                    kind = "dart_sign"
                elif column in (0, 1) and abs(amount.value) in {abs(v) for v in values[1 - column]} and abs(amount.value) > 999:
                    kind = "wrong_period"
                elif any(abs(amount.value) * scale in {abs(v) for v in values[column]}
                         or (abs(amount.value) % scale == 0 and abs(amount.value) // scale in {abs(v) for v in values[column]})
                         for scale in SCALES):
                    kind = "unit_mismatch"
                elif any(key[:6] in line and re.sub(r"\s+", "", amount.printed) in line
                         for line in text_lines.get(amount.cell.page, [])):
                    kind = "pdf_only"
                else:
                    kind = "unconfirmed"
                counts[kind] += 1
                is_flagged = (s_index, r_index, column) in flagged
                flagged_counts[kind] += is_flagged
                if kind in ("wrong_period", "unit_mismatch", "pdf_only", "unconfirmed"):
                    attention.append({"label": row.label, "period": column, "printed": amount.printed,
                                      "value": amount.value, "class": kind, "flagged": is_flagged,
                                      "dart_same_name": sorted(v for v, names in values[column].items() if key in names)})
        missing = [{"period": period, "value": value, "dart_names": sorted(names)}
                   for period in (0, 1) for value, names in values[period].items()
                   if value and value not in ours[period] and -value not in ours[period]]
        statements.append({"title": statement.title, "page": statement.page, "opendart": division,
                           "rows": len(statement.rows),
                           "cells": sum(counts.values()), "classes": counts, "flagged_by_class": flagged_counts,
                           "attention": attention, "dart_not_extracted": missing, "problems": statement.problems})
    return {"statements": statements}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--reader", choices=("rules", "ai"), default="rules")
    parser.add_argument("--out", type=Path, required=True, help="folder for <reader>.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "cache")
    parser.add_argument("--online", action="store_true", help="fetch OpenDART responses missing from the cache")
    parser.add_argument("--only", nargs="*", help="company names to measure")
    args = parser.parse_args()

    from dart_review.documents import extract
    from dart_review.documents.vision import PROMPT_VERSION, OllamaVision
    client = DartClient(ResponseCache(args.cache), offline=not args.online)
    results = []
    for document in DOCUMENTS:
        if args.only and document["company"] not in args.only:
            continue
        path = args.pdf_dir.expanduser() / document["file"]
        data = path.read_bytes()
        items = OpenDart(client, document["corp_code"])
        model = OllamaVision() if args.reader == "ai" else None
        started = time.monotonic()
        try:
            extraction = extract(path, ocr="auto", reader=args.reader, model=model)
        except Exception as exc:  # recorded, so a document the reader cannot open is not dropped from the record
            results.append({"company": document["company"], "file": document["file"], "reader": args.reader,
                            "sha256": hashlib.sha256(data).hexdigest(), "failed": f"{type(exc).__name__}: {exc}"[:300]})
            print(f"{document['company']}: failed ({type(exc).__name__})", flush=True)
            continue
        seconds = round(time.monotonic() - started)
        result = {"company": document["company"], "corp_code": document["corp_code"], "file": document["file"],
                  "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "reader": args.reader,
                  "seconds": seconds, "model": model.name if model else None,
                  "prompt_version": PROMPT_VERSION if model else None,
                  "model_calls": len(model.calls) if model else None,
                  "cells": len(extraction.checks), "needs_review": extraction.needs_review,
                  "document_problems": [p for p in extraction.problems if not p.startswith("AI 호출")],
                  **classify(extraction, items, printed_on_page(path))}
        results.append(result)
        silent = sum(1 for s in result["statements"] for item in s.get("attention", [])
                     if item["class"] in ("wrong_period", "unit_mismatch", "unconfirmed") and not item["flagged"])
        print(f"{document['company']}: {seconds}s, cells {result['cells']}, review {result['needs_review']}, "
              f"unconfirmed and unmarked {silent}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.reader}.json"
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "dart_review"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip())
    target.write_text(json.dumps({"code_commit": commit, "code_changed_since_commit": dirty, "opendart": {"year": YEAR, "report": REPORT, "fs_div": "CFS or OFS"},
                                  "documents": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
