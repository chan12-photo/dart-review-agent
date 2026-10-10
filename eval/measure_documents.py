"""Measure the document reader on real reports against OpenDART (v0.2; a measurement, not an evaluation).

    python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out eval/documents_2026-10-10
    python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader ai   --out eval/documents_2026-10-10

The PDFs are public reports but are not committed; each is identified by its SHA-256 and size. OpenDART
(fnlttSinglAcntAll, annual; CFS for 연결 statements, OFS for 별도) is read from the response cache.

Classification v2 (after Codex's D4 review: v1 counted a same value under another account, any opposite sign,
and any same-line number as right, and lost missing rows whose value was elsewhere). A cell is (statement,
row, period, value), and its value and its label are judged apart.

Value, matched one to one with OpenDART's items of the statement and period:
- correct: dart_exact (same name and value), dart_value (same value; the name is judged under "label"),
  dart_sign_cf (opposite sign in a 현금흐름표, where companies store outflows either way),
  sign_as_printed (opposite sign elsewhere, but the text layer prints it so on this row in this period's slot:
  an expense in parentheses that OpenDART stores positive),
  pdf_confirmed (not in OpenDART, but the PDF's text layer prints this value on this row's line in this
  period's slot under its label, and the unit is confirmed by a cell matching OpenDART exactly in a statement
  of the same unit in this document)
- wrong: wrong_period (OpenDART has it only in the other period), unit_mismatch (only after a factor of
  10^3, 10^6 or 10^8)
- review: sign_review (opposite sign outside a 현금흐름표), unconfirmed (none of the above)
Label: label_ok (equals the label printed on the cell's line in the text layer, or OpenDART's name of the
matched item), label_differs (differs from the printed label: a wrong label), label_review (no printed line to
compare and OpenDART's name differs: a person compares), label_unknown.
Missing: OpenDART items of the statement left unmatched; each is "reported" when a statement or document
problem names its printed number, "generic" when only a message without numbers covers it (a band the model
could not read), else "silent". A person then separates values OpenDART presents differently from values the
workbook really lacks.
A wrong or review cell, or a label_differs cell, without a "확인 필요" mark is a candidate silent error.
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
CORRECT = ("dart_exact", "dart_value", "dart_sign_cf", "sign_as_printed", "pdf_confirmed")
WRONG = ("wrong_period", "unit_mismatch")
REVIEW = ("sign_review", "unconfirmed")
SCALES = (10 ** 3, 10 ** 6, 10 ** 8)
RENDER_SCALE = 2.0  # the AI reader's cells from a text layer are in rendered pixels


def name_key(name: str) -> str:
    name = re.sub(r"\s+|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.|^\d+\.|\(주석[^)]*\)|[·ㆍ.,]", "", name)
    return re.sub(r"\([^)]*\)$", "", name)


def integer(text: str | None) -> int | None:
    text = (text or "").replace(",", "").strip()
    return int(text) if re.fullmatch(r"-?\d+", text) else None


class OpenDart(dict):
    """CFS or OFS items, fetched from the cache only when a statement needs them."""

    def __init__(self, client: DartClient, corp_code: str):
        super().__init__()
        self.client, self.corp_code = client, corp_code

    def __missing__(self, division: str) -> list[dict]:
        self[division] = self.client.financial_statements(self.corp_code, YEAR, REPORT, division).json()["list"]
        return self[division]


def dart_items_for(items: list[dict], kind: str) -> list[dict]:
    """OpenDART's items of the statement kind (IS falls back to CIS and back, as companies file either)."""
    present = {item["sj_div"] for item in items}
    if kind not in present:
        kind = {"IS": "CIS", "CIS": "IS"}.get(kind, kind)
    return [item for item in items if item["sj_div"] == kind]


def text_lines(path: Path) -> dict[int, list]:
    from dart_review.documents.table import group_lines
    from dart_review.documents.words import text_layer_words
    lines: dict[int, list] = {}
    for line in group_lines(text_layer_words(path)):
        lines.setdefault(line.page, []).append(line)
    return lines


_NOTE_REF = re.compile(r"\d{1,2}(\s*,\s*\d{1,2})*")


def printed_slot(cell, lines_by_page: dict[int, list], scale: float):
    """(printed label, period slot of the cell's amount, number of slots) from the text-layer line where the cell
    is printed; None when the cell has no position or no text-layer word is there."""
    from dart_review.documents.statement import clean_label, without_section_column
    if cell.method == "ai" or not cell.x1:
        return None
    x0, x1, top, bottom = cell.x0 / scale, cell.x1 / scale, cell.top / scale, cell.bottom / scale
    centre = (top + bottom) / 2
    for line in lines_by_page.get(cell.page, []):
        if not (line.top - 1 <= centre <= line.bottom + 1):
            continue
        slots = [c for c in line.cells if c.is_amount and not _NOTE_REF.fullmatch(c.text.strip())]
        hit = next((i for i, c in enumerate(slots) if c.x0 < x1 and x0 < c.x1), None)
        if hit is None:
            continue
        words = without_section_column([c for c in line.cells if not c.is_amount and re.search(r"[가-힣]", c.text)])
        label = clean_label(" ".join(c.text for c in words))
        return label, hit, len(slots)
    return None


def classify(extraction, items_by_division, lines_by_page: dict[int, list], scale: float = 1.0) -> dict:
    flagged = {(c.statement, c.row, c.column) for c in extraction.checks if c.status == "확인 필요"}
    # units confirmed in this document: a statement with a cell matching OpenDART exactly (name, value, period)
    units_confirmed = set()
    for statement in extraction.statements:
        if statement.kind == "SCE":
            continue
        items = dart_items_for(items_by_division["OFS" if statement.title.startswith("별도") else "CFS"], statement.kind)
        exact = {(name_key(item["account_nm"]), integer(item.get(field)), period) for item in items
                 for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount"))}
        if any((name_key(row.label), amount.value, column) in exact for row in statement.rows
               for column, amount in row.amounts.items() if amount.value):
            units_confirmed.add(statement.unit_text)
    problems_all = " ".join(extraction.problems)
    statements = []
    for s_index, statement in enumerate(extraction.statements):
        if statement.kind == "SCE":
            statements.append({"title": statement.title, "page": statement.page, "skipped": True,
                               "problems": statement.problems})
            continue
        division = "OFS" if statement.title.startswith("별도") else "CFS"
        items = dart_items_for(items_by_division[division], statement.kind)
        is_cf = statement.kind == "CF"

        def in_slot(cell, columns=len(statement.columns)):
            """The text layer prints this cell's number on its row's line, in its period's slot, under its label."""
            slot = cell["slot"]
            return bool(slot and slot[2] == columns and slot[1] == cell["period"] and slot[0]
                        and name_key(slot[0]) == name_key(cell["label"]))
        cells = []
        for r_index, row in enumerate(statement.rows):
            for column, amount in row.amounts.items():
                if amount.value is None or column > 1:
                    continue
                cells.append({"row": r_index, "label": row.label, "period": column, "printed": amount.printed,
                              "value": amount.value, "flagged": (s_index, r_index, column) in flagged,
                              "slot": printed_slot(amount.cell, lines_by_page, scale)})
        # OpenDART's values, one entry per item and period (a value printed twice is two entries)
        pool = [{"name": name_key(item["account_nm"]), "period": period, "value": value, "used": False}
                for item in items for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount"))
                if (value := integer(item.get(field))) is not None and value != 0]

        def take(cell, test):
            entry = next((e for e in pool if not e["used"] and e["period"] == cell["period"] and test(e)), None)
            if entry is not None:
                entry["used"] = True
            return entry

        for cell in cells:  # pass 1: same name and value
            entry = take(cell, lambda e, c=cell: e["value"] == c["value"] and e["name"] == name_key(c["label"]))
            if entry:
                cell["class"], cell["dart_name"] = "dart_exact", entry["name"]
        for cell in cells:  # pass 2: same value, another name
            if "class" not in cell and (entry := take(cell, lambda e, c=cell: e["value"] == c["value"])):
                cell["class"], cell["dart_name"] = "dart_value", entry["name"]
        for cell in cells:  # pass 3: opposite sign
            if "class" not in cell and (entry := take(cell, lambda e, c=cell: e["value"] == -c["value"])):
                # outside a 현금흐름표 the sign is right only as the statement prints it ("(9,826,868)" for an
                # expense that OpenDART stores positive): the text layer must show it on this row in this period
                cell["class"] = ("dart_sign_cf" if is_cf else "sign_as_printed" if in_slot(cell) else "sign_review")
                cell["dart_name"] = entry["name"]
        unit_known = any(cell.get("class") == "dart_exact" for cell in cells) or statement.unit_text in units_confirmed
        for cell in cells:
            if "class" in cell:
                continue
            others = {abs(e["value"]) for e in pool if e["period"] == 1 - cell["period"]}
            same = {abs(e["value"]) for e in pool if e["period"] == cell["period"]}
            magnitude = abs(cell["value"])
            slot = cell["slot"]
            if magnitude in others and magnitude > 999:
                cell["class"] = "wrong_period"
            elif any(magnitude * k in same or (magnitude % k == 0 and magnitude // k in same) for k in SCALES):
                cell["class"] = "unit_mismatch"
            elif in_slot(cell) and unit_known:
                cell["class"] = "pdf_confirmed"
            else:
                cell["class"] = "unconfirmed"
        for cell in cells:  # the label
            slot = cell["slot"]
            if slot and slot[0]:
                cell["label_class"] = "label_ok" if name_key(slot[0]) == name_key(cell["label"]) else "label_differs"
                cell["printed_label"] = slot[0]
            elif cell.get("dart_name"):
                cell["label_class"] = "label_ok" if cell["dart_name"] == name_key(cell["label"]) else "label_review"
            else:
                cell["label_class"] = "label_unknown"
        text = " ".join(statement.problems) + " " + problems_all
        # numbers a problem names, as quoted there ('47', '(2,447) 원'); a page number ("10쪽") is not one
        digits_reported = {re.sub(r"[^\d,]", "", quoted) for quoted in re.findall(r"'([^']*\d[^']*)'", text)}
        generic = "한 부분을 읽지 못했다" in text
        missing = []
        for entry in pool:
            if entry["used"]:
                continue
            unit = statement.unit or 1
            printed = f"{abs(entry['value']) // unit:,}" if entry["value"] % unit == 0 else None
            status = ("reported" if printed and printed in digits_reported else "generic" if generic else "silent")
            missing.append({"period": entry["period"], "value": entry["value"], "dart_name": entry["name"],
                            "status": status})
        count = lambda key, values: {v: sum(1 for c in cells if c[key] == v) for v in values}
        classes = count("class", CORRECT + WRONG + REVIEW)
        labels = count("label_class", ("label_ok", "label_differs", "label_review", "label_unknown"))
        silent = [c for c in cells if not c["flagged"] and (c["class"] in WRONG + REVIEW or c["label_class"] == "label_differs")]
        statements.append({
            "title": statement.title, "page": statement.page, "opendart": division, "rows": len(statement.rows),
            "cells": len(cells), "flagged": sum(c["flagged"] for c in cells), "classes": classes, "labels": labels,
            "sums_checked": statement.sums_checked,
            "silent_candidates": [{k: c[k] for k in ("label", "period", "printed", "class", "label_class")} for c in silent],
            "review": [{k: c.get(k) for k in ("label", "period", "printed", "class", "label_class", "dart_name",
                                              "printed_label", "flagged")}
                       for c in cells if c["class"] in WRONG + REVIEW or c["label_class"] in ("label_differs", "label_review")],
            "missing": missing, "problems": statement.problems})
    return {"statements": statements}


def summary(result: dict) -> dict:
    """The counts of one document, for the console and the report."""
    statements = [s for s in result.get("statements", []) if not s.get("skipped")]
    total = lambda key: sum(s[key] for s in statements)
    group = lambda names: sum(s["classes"][n] for s in statements for n in names)
    missing = [m for s in statements for m in s["missing"]]
    return {"cells": total("cells"), "flagged": total("flagged"), "correct": group(CORRECT), "wrong": group(WRONG),
            "review": group(REVIEW), "label_differs": sum(s["labels"]["label_differs"] for s in statements),
            "label_review": sum(s["labels"]["label_review"] for s in statements),
            "silent_candidates": sum(len(s["silent_candidates"]) for s in statements),
            "missing": len(missing), "missing_silent": sum(m["status"] == "silent" for m in missing),
            "missing_generic": sum(m["status"] == "generic" for m in missing),
            "sums_checked": sum(s["sums_checked"] or 0 for s in statements)}


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
                  **classify(extraction, items, text_lines(path), RENDER_SCALE if args.reader == "ai" else 1.0)}
        results.append(result)
        tally = summary(result)
        print(f"{document['company']}: {seconds}s, " + ", ".join(f"{k} {v}" for k, v in tally.items()), flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"{args.reader}.json"
    import subprocess
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "dart_review"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip())
    target.write_text(json.dumps({"classification": "v2", "code_commit": commit, "code_changed_since_commit": dirty,
                                  "opendart": {"year": YEAR, "report": REPORT, "fs_div": "CFS or OFS"},
                                  "documents": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
