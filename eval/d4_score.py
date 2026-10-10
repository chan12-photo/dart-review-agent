"""D4 scorer (contract 4.3, 4.4, 5): the product's checked values against the gold of eval/d4_gold.py.

    python eval/d4_score.py --pdf report.pdf --gold gold.json --reader rules --out score.json

The product is run on the PDF (``extract``) and its values are taken in the API's report format
(dart_review/server.report). Each gold cell (statement, printed label, period) is matched to the product:
- correct: a cell of the same statement, label, and period with the gold's value
- value wrong: the same statement, label, and period, another value                      -> S1 when unmarked
- label wrong: no cell of that label and period, but an unused cell of that period with the gold's value
  under another label                                                                    -> L1 when unmarked
- missing: none of these                         -> S2 when no problem of the statement quotes its number
A missing cell in a statement with only the generic "AI가 한 부분을 읽지 못했다" is counted in G1 as well;
the generic message does not mark it. Product cells left unmatched are "not in gold" (a person reviews them).
Labels are compared without spaces, item markers ("1.", "가.", "Ⅰ."), and note references.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GENERIC = "한 부분을 읽지 못했다"


def label_key(label: str) -> str:
    label = re.sub(r"\(\s*주\s*석?\s*[\d,\s]+\)\s*$", "", label or "")
    label = re.sub(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVXlI|]{1,4}\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*", "", label)
    return re.sub(r"\s+", "", label)


def quoted_numbers(problems: list[str]) -> set[str]:
    return {re.sub(r"[^\d,]", "", quoted) for problem in problems for quoted in re.findall(r"'([^']*\d[^']*)'", problem)}


def score(gold: dict, report: dict) -> dict:
    by_title: dict[str, list[dict]] = {}
    for statement in report["statements"]:
        by_title.setdefault(statement["title"], []).append(statement)
    document_problems = report.get("problems", [])
    results = []
    for g_statement in gold["statements"]:
        if g_statement["kind"] == "SCE":
            continue
        gold_cells = [c for c in gold["cells"] if c["statement"] == g_statement["title"]]
        candidates = by_title.get(g_statement["title"], [])
        product = min(candidates, key=lambda s: abs(s["page"] - g_statement["page"]), default=None)
        cells = []
        if product is not None:
            for row in product["rows"]:
                for value in row["values"]:
                    if value["value"] is None or value["column"] > 1:
                        continue
                    cells.append({"label": row["label"], "key": label_key(row["label"]), "period": value["column"],
                                  "value": value["value"], "printed": value["printed"], "page": value.get("page"),
                                  "flagged": value["status"] == "확인 필요", "used": False})
        problems = (product["problems"] if product else []) + document_problems
        quoted = quoted_numbers(problems)
        generic = any(GENERIC in problem for problem in problems)
        outcome = []
        for g in gold_cells:  # pass 1: same label and period
            key = label_key(g["label"])
            match = next((c for c in cells if not c["used"] and c["key"] == key and c["period"] == g["period"]), None)
            if match:
                match["used"] = True
                outcome.append((g, "correct" if match["value"] == g["value"] else "value_wrong", match))
            else:
                outcome.append((g, None, None))
        for index, (g, result, _) in enumerate(outcome):  # pass 2: the gold's value under another label
            if result is None:
                match = next((c for c in cells if not c["used"] and c["period"] == g["period"] and c["value"] == g["value"]), None)
                if match:
                    match["used"] = True
                    outcome[index] = (g, "label_wrong", match)
                else:
                    outcome[index] = (g, "missing", None)
        rows = []
        for g, result, match in outcome:
            entry = {"label": g["label"], "period": g["period"], "printed": g["printed"], "gold_value": g["value"],
                     "page": g["page"], "result": result}
            if match:
                entry.update(product_label=match["label"], product_value=match["value"], flagged=match["flagged"])
            else:
                number = re.sub(r"[^\d,]", "", g["printed"])
                entry.update(flagged=number in quoted, generic=generic)
            rows.append(entry)
        extra = [{k: c[k] for k in ("label", "period", "printed", "value", "flagged")} for c in cells if not c["used"]]
        count = lambda result, flagged=None: sum(1 for r in rows if r["result"] == result
                                                 and (flagged is None or r["flagged"] == flagged))
        results.append({
            "statement": g_statement["title"], "page": g_statement["page"], "found": product is not None,
            "gold_cells": len(rows), "product_cells": len(cells),
            "correct": count("correct"), "value_wrong": count("value_wrong"), "label_wrong": count("label_wrong"),
            "missing": count("missing"),
            "S1": count("value_wrong", False), "L1": count("label_wrong", False), "S2": count("missing", False),
            "G1": sum(1 for r in rows if r["result"] == "missing" and not r["flagged"] and r.get("generic")),
            "flagged": sum(c["flagged"] for c in cells), "not_in_gold": extra,
            "sums_checked": product.get("sums_checked") if product else None,
            "problems": problems if product else ["재무제표를 찾지 못했다"],
            "cells": [r for r in rows if r["result"] != "correct"]})
    totals = {key: sum(r[key] for r in results) for key in ("gold_cells", "product_cells", "correct", "value_wrong",
                                                            "label_wrong", "missing", "S1", "L1", "S2", "G1", "flagged")}
    totals["not_in_gold"] = sum(len(r["not_in_gold"]) for r in results)
    totals["statements_not_found"] = sum(not r["found"] for r in results)
    return {"totals": totals, "statements": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--reader", choices=("rules", "ai"), default="ai")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from dart_review.documents import extract
    from dart_review.server import report
    extraction = extract(args.pdf, ocr="auto", reader=args.reader)
    data = report(extraction, args.pdf.name, args.reader)
    result = score(json.loads(args.gold.read_text(encoding="utf-8")), data)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
