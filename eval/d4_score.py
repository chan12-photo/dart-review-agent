"""D4 scorer (contract 4.3-5): the product's checked values against the confirmed gold of eval/d4_gold.py.

    python eval/d4_score.py --pdf report.pdf --gold gold.json --mapping mapping.json \
        [--extras extras.json] --reader ai --out score.json

The gold is applied with the mapping a person confirmed (d4_gold.apply_mapping); without a decision for every
mapping item the scorer stops. The product is run on the PDF and read in the API's report format.

Statements are matched by the gold's statement id: the product statement of the same title whose page is in the
gold statement's page range (each used once). Each gold cell (statement, printed label, period) is then:
- correct: a product cell of that label and period with the gold value (for a printed "-": no product value)
- value wrong: that label and period with another value, or a value where the print has "-"   -> S1 if unmarked
- label wrong: no cell of that label and period, but an unused cell of that period with the gold
  value under another label                                                                -> L1 if unmarked
- missing: none of these. It is pointed at only by a problem that names its number and either its row (label)
  or its row and period, or names its number while that number is printed only once in the statement;
  a number alone that is printed on several rows points at none of them                   -> S2 if not pointed at
  A missing cell in a statement with the generic "AI가 한 부분을 읽지 못했다" is counted in G1 too.
Product cells left over ("not in gold") need a person's verdict in --extras ("wrong" or "ok", by key). An
unmarked extra judged wrong counts in S1; an unmarked extra without a verdict makes the result incomplete (no
official verdict). Labels are compared without spaces, item markers, and note references.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.d4_gold import apply_mapping  # noqa: E402

GENERIC = "한 부분을 읽지 못했다"
PERIOD_WORDS = {0: ("당기",), 1: ("전기",)}


def label_key(label: str) -> str:
    label = re.sub(r"\(\s*주\s*석?\s*[\d,\s]+\)\s*$", "", label or "")
    label = re.sub(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVXlI|]{1,4}\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*", "", label)
    return re.sub(r"\s+", "", label)


def digits(text: str) -> str:
    return re.sub(r"[^\d,]", "", text or "").strip(",")


# where a problem points: "10쪽 '매출액' 줄: 원본의 금액 '47'…" (AI reader), "1쪽 '47' (기본주당이익)" (rules reader)
AI_POINT = re.compile(r"(\d+)쪽(?: '([^']+)' 줄)?: (?:원본의|OCR이 읽은) 금액 '([^']+)'")
RULES_POINT = re.compile(r"(\d+)쪽 '([^']+)'(?: \(([^)]*)\))?")


def pointers(problems: list[str]) -> list[dict]:
    """(page, label, number) a problem names; label or page None when it does not say."""
    found = []
    for problem in problems:
        hits = [{"page": int(m.group(1)), "label": m.group(2), "number": digits(m.group(3))}
                for m in AI_POINT.finditer(problem)]
        if not hits:
            hits = [{"page": int(m.group(1)), "label": m.group(3), "number": digits(m.group(2))}
                    for m in RULES_POINT.finditer(problem) if re.search(r"\d", m.group(2))]
        if not hits:  # any other quoted number, with no row
            hits = [{"page": None, "label": None, "number": digits(q)} for q in re.findall(r"'([^']*\d[^']*)'", problem)]
        found += [hit | {"text": problem} for hit in hits if hit["number"]]
    return found


def pointed(cell: dict, marks: list[dict], problems: list[str], unique: bool) -> bool:
    number, key = digits(cell["printed"]), label_key(cell["label"])
    for mark in marks:
        if mark["number"] != number or (mark["page"] is not None and mark["page"] != cell["page"]):
            continue
        if (mark["label"] and label_key(mark["label"]) == key) or (not mark["label"] and unique):
            return True
    # a problem that names the row and then the period ("유동자산 당기 칸을 읽지 못했다")
    return bool(key) and any(key + word in re.sub(r"\s+", "", problem)
                             for problem in problems for word in PERIOD_WORDS[cell["period"]])


def extra_key(statement_id: str, cell: dict) -> str:
    return f"{statement_id}|{cell['label']}|{cell['period']}|{cell['printed']}"


def score(gold: dict, report: dict, extras: dict | None = None) -> dict:
    extras = extras or {}
    unused = list(report["statements"])
    document_problems = report.get("problems", [])
    results = []
    for g_statement in gold["statements"]:
        if g_statement["kind"] == "SCE":
            continue
        first, last = g_statement["page"], g_statement.get("end_page", g_statement["page"])
        product = next((s for s in unused if s["title"] == g_statement["title"] and first <= s["page"] <= last), None)
        if product is not None:
            unused.remove(product)
        gold_cells = [c for c in gold["cells"] if c["statement_id"] == g_statement["id"]]
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
        marks = pointers(problems)
        generic = any(GENERIC in problem for problem in problems)
        printed_count = Counter(digits(c["printed"]) for c in gold_cells if c["value"] is not None)
        outcome = []
        for g in gold_cells:  # pass 1: same label and period
            match = next((c for c in cells if not c["used"] and c["key"] == label_key(g["label"])
                          and c["period"] == g["period"]), None)
            if match:
                match["used"] = True
                if g["value"] is None:  # the print has "-": any value here is wrong
                    outcome.append((g, "value_wrong", match))
                else:
                    outcome.append((g, "correct" if match["value"] == g["value"] else "value_wrong", match))
            else:
                outcome.append((g, None, None))
        for index, (g, result, _) in enumerate(outcome):  # pass 2: the gold value under another label
            if result is not None:
                continue
            if g["value"] is None:
                outcome[index] = (g, "dash", None)  # printed "-", nothing in the workbook: right
                continue
            match = next((c for c in cells if not c["used"] and c["period"] == g["period"] and c["value"] == g["value"]), None)
            if match:
                match["used"] = True
                outcome[index] = (g, "label_wrong", match)
            else:
                outcome[index] = (g, "missing", None)
        rows = []
        for g, result, match in outcome:
            if result == "dash":
                continue
            entry = {"label": g["label"], "period": g["period"], "printed": g["printed"], "gold_value": g["value"],
                     "page": g["page"], "result": result}
            if match:
                entry.update(product_label=match["label"], product_value=match["value"], flagged=match["flagged"])
            else:
                unique = printed_count[digits(g["printed"])] == 1
                entry.update(flagged=pointed(g, marks, problems, unique), generic=generic)
            rows.append(entry)
        extra = []
        for c in cells:
            if c["used"]:
                continue
            key = extra_key(g_statement["id"], c)
            extra.append({"key": key, "label": c["label"], "period": c["period"], "printed": c["printed"],
                          "value": c["value"], "flagged": c["flagged"], "verdict": extras.get(key)})
        count = lambda result, flagged=None: sum(1 for r in rows if r["result"] == result
                                                 and (flagged is None or r["flagged"] == flagged))
        extra_wrong_unmarked = sum(1 for x in extra if not x["flagged"] and x["verdict"] == "wrong")
        results.append({
            "statement_id": g_statement["id"], "statement": g_statement["title"], "page": g_statement["page"],
            "found": product is not None, "gold_cells": len(rows), "product_cells": len(cells),
            "correct": count("correct"), "value_wrong": count("value_wrong"), "label_wrong": count("label_wrong"),
            "missing": count("missing"),
            "S1": count("value_wrong", False) + extra_wrong_unmarked, "L1": count("label_wrong", False),
            "S2": count("missing", False),
            "G1": sum(1 for r in rows if r["result"] == "missing" and not r["flagged"] and r.get("generic")),
            "flagged": sum(c["flagged"] for c in cells), "not_in_gold": extra,
            "unjudged_extras": sum(1 for x in extra if not x["flagged"] and x["verdict"] is None),
            "sums_checked": product.get("sums_checked") if product else None,
            "problems": problems if product else ["재무제표를 찾지 못했다"],
            "cells": [r for r in rows if r["result"] != "correct"]})
    keys = ("gold_cells", "product_cells", "correct", "value_wrong", "label_wrong", "missing", "S1", "L1", "S2", "G1",
            "flagged", "unjudged_extras")
    totals = {key: sum(r[key] for r in results) for key in keys}
    totals["not_in_gold"] = sum(len(r["not_in_gold"]) for r in results)
    totals["statements_not_found"] = sum(not r["found"] for r in results)
    # product statements no gold statement took (a 자본변동표 has no rows: the product does not read it)
    totals["product_statements_not_in_gold"] = [s["title"] for s in unused if s["rows"]]
    totals["complete"] = totals["unjudged_extras"] == 0 and totals["statements_not_found"] == 0
    return {"totals": totals, "statements": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, help="the decisions a person confirmed for the gold's mapping items")
    parser.add_argument("--extras", type=Path, help="a person's verdicts on product cells not in the gold")
    parser.add_argument("--reader", choices=("rules", "ai"), default="ai")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {"decisions": {}}
    try:
        gold = apply_mapping(gold, mapping)
    except ValueError as exc:
        print(f"the gold is not confirmed: {exc}")
        return 2
    extras = json.loads(args.extras.read_text(encoding="utf-8")) if args.extras else {}
    from dart_review.documents import extract
    from dart_review.server import report
    extraction = extract(args.pdf, ocr="auto", reader=args.reader)
    data = report(extraction, args.pdf.name, args.reader)
    result = score(gold, data, extras.get("verdicts", {}))
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
