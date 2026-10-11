"""D4 scorer (contract 4.3-5): the product's checked values against the confirmed gold of eval/d4_gold.py.

    python eval/d4_score.py --pdf report.pdf --report report.ai.json --gold gold.json --mapping mapping.json \
        --reader ai --out score.json                    # runs the product and saves its report first
    python eval/d4_score.py --report report.ai.json --gold gold.json --mapping mapping.json \
        --extras extras.json --out score.json           # scores a saved report with a person's verdicts

The gold is applied with the mapping (d4_gold.apply_mapping); without a valid decision for every mapping item the
scorer stops. The product's output is the API's report format, saved once: a person's verdicts on cells outside
the gold name cells of that saved report (by id and by the report's SHA-256), so they never apply to another run.

Statements are matched by the gold's statement id: the product statement of the same title whose page is in the
gold statement's page range (each used once). Each gold cell (statement, printed label, period) is then:
- correct: a product cell of that label and period with the gold value
- value wrong: that label and period with another value                                     -> S1 if unmarked
- label wrong: no cell of that label and period, but an unused cell of that period with the gold
  value under another label                                                                -> L1 if unmarked
- missing: none of these                                                           -> S2 if not pointed at
- a printed "-": right when the product has no value there; a value there is "dash filled"  -> S1 if unmarked
Only printed amounts (not "-") are gold cells: the denominator does not depend on the product.
A missing cell is pointed at only by the product's structured reports of an amount it did not place (``pointers``):
the report names the page and the printed number, and the row and period when it knows them; the gold cells it
fits must be one printed place (one page, row, and period), and each report points at one cell. A missing cell in
a statement with the generic "AI가 한 부분을 읽지 못했다" is counted in G1 too.
Product cells left over, also those of product statements no gold statement took, are "not in gold": each unmarked
one needs a person's verdict ("wrong" or "ok", with a note) by its id ("statement/row/column" of the report). An
unmarked extra judged wrong counts in S1. Labels are compared without spaces, item markers, and note references.
The status separates what is done: machine scored; mapping confirmed by a person; extras judged by a person; and
official (all of these, on a saved report).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.d4_gold import apply_mapping  # noqa: E402

GENERIC = "한 부분을 읽지 못했다"
PERIODS = {"당기": 0, "전기": 1}
VERDICTS = ("wrong", "ok")


def label_key(label: str) -> str:
    label = re.sub(r"\(\s*주\s*석?\s*[\d,\s]+\)\s*$", "", label or "")
    label = re.sub(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVXlI|]{1,4}\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*", "", label)
    return re.sub(r"\s+", "", label)


def digits(text: str) -> str:
    return re.sub(r"[^\d,]", "", text or "").strip(",")


# The product's two structured reports of an amount it did not place (contract 4.4); no other wording points at a
# cell. The AI reader: "10쪽 '매출액' 줄 전기: 원본의 금액 '47'를 AI가 읽지 않았다", "3쪽 당기: …" (a line without a
# label), "5쪽 '매출액' 줄: OCR이 읽은 금액 '1,234'를 AI가 읽지 않았다" (a photo: no period).
UNREAD = re.compile(r"(\d+)쪽(?: '([^']+)' 줄)?(?: (당기|전기|\d+번째 기간))?: (?:원본의|OCR이 읽은) 금액 '([^']+)'"
                    r"를 AI가 읽지 않았다")
# The rules reader: "표에 넣지 못한 금액 2개 (1쪽 '기타(손실)' 줄 '47', 2쪽 '1,000' 외 1개): 줄이나 열을 …" (it names
# twelve). A label with a quote (') in it is not parsed: its report then points at nothing.
ORPHANS = re.compile(r"^표에 넣지 못한 금액 \d+개 \((.*)\): 줄이나 열을")
ORPHAN = re.compile(r"(\d+)쪽(?: '([^']+)' 줄)? '([^']+)'")


def _period(word: str | None) -> int | None:
    if word is None:
        return None
    return PERIODS.get(word, int(re.sub(r"\D", "", word) or 0) - 1)


def pointers(problems: list[str]) -> list[dict]:
    """(page, label, period, number) of each amount a structured report names; label or period None when the
    report does not say."""
    found = []
    for problem in problems:
        hits = [(m.group(1), m.group(2), _period(m.group(3)), m.group(4)) for m in UNREAD.finditer(problem)]
        listed = ORPHANS.match(problem)
        if listed:
            hits += [(m.group(1), m.group(2), None, m.group(3)) for m in ORPHAN.finditer(listed.group(1))]
        found += [{"page": int(page), "label": label, "period": period, "number": digits(number), "text": problem}
                  for page, label, period, number in hits if digits(number)]
    return found


def _place(cell: dict) -> tuple:
    return cell["page"], label_key(cell["label"]), cell["period"]


def covered(marks: list[dict], gold_cells: list[dict], missing: set[int]) -> set[int]:
    """The indices of the missing gold cells the reports point at. The printed cells a report fits (its page and
    number, and its row and period when it names them) must all be one printed place, else it points at none: the
    same number in both periods of the named row, or on two rows of the page when no row is named. Each report
    points at one cell (two missing cells of one place need two reports)."""
    done: set[int] = set()
    for mark in marks:
        fits = [i for i, g in enumerate(gold_cells) if g["value"] is not None and g["page"] == mark["page"]
                and digits(g["printed"]) == mark["number"]
                and (mark["label"] is None or label_key(g["label"]) == label_key(mark["label"]))
                and (mark["period"] is None or g["period"] == mark["period"])]
        if len({_place(gold_cells[i]) for i in fits}) != 1:
            continue
        free = [i for i in fits if i in missing and i not in done]
        if free:
            done.add(free[0])
    return done


def _product_cells(index: int, statement: dict) -> list[dict]:
    """Every value the workbook has for this statement (all periods), with its id "statement/row/column"."""
    return [{"id": f"{index}/{r_index}/{value['column']}", "label": row["label"], "key": label_key(row["label"]),
             "period": value["column"], "value": value["value"], "printed": value["printed"], "page": value.get("page"),
             "flagged": value["status"] == "확인 필요", "used": False}
            for r_index, row in enumerate(statement["rows"]) for value in row["values"] if value["value"] is not None]


def _extra(cell: dict, statement: dict) -> dict:
    return {"id": cell["id"], "statement": statement["title"], "statement_page": statement["page"],
            "page": cell["page"], "label": cell["label"], "period": cell["period"], "printed": cell["printed"],
            "value": cell["value"], "flagged": cell["flagged"]}


def check_verdicts(extras: dict, ids: set[str], report_sha256: str | None) -> dict[str, str]:
    """The verdicts of ``extras`` by cell id. Each must name a cell outside the gold, be "wrong" or "ok", and have a
    note; verdicts must name the report they judge (its SHA-256) when it is known, and who judged."""
    verdicts = extras.get("verdicts") or {}
    if not verdicts:
        return {}
    if report_sha256 is not None and extras.get("report_sha256") != report_sha256:
        raise ValueError("the verdicts are for another report (report_sha256 differs)")
    if not extras.get("judged_by"):
        raise ValueError("the verdicts do not say who judged them (judged_by)")
    unknown = sorted(set(verdicts) - ids)
    if unknown:
        raise ValueError(f"verdicts for {len(unknown)} cell(s) not outside the gold: {', '.join(unknown[:10])}")
    found = {}
    for cell_id, verdict in verdicts.items():
        if not isinstance(verdict, dict) or verdict.get("verdict") not in VERDICTS or not str(verdict.get("note") or "").strip():
            raise ValueError(f"{cell_id}: a verdict is {{\"verdict\": \"wrong\" or \"ok\", \"note\": the reason}}, not {verdict!r}")
        found[cell_id] = verdict["verdict"]
    return found


def score(gold: dict, report: dict, extras: dict | None = None, report_sha256: str | None = None) -> dict:
    extras = extras or {}
    unused = list(enumerate(report["statements"]))
    document_problems = report.get("problems", [])
    results = []
    for g_statement in gold["statements"]:
        if g_statement["kind"] == "SCE":
            continue
        first, last = g_statement["page"], g_statement.get("end_page", g_statement["page"])
        found = next(((i, s) for i, s in unused if s["title"] == g_statement["title"] and first <= s["page"] <= last), None)
        if found is not None:
            unused.remove(found)
        index, product = found if found is not None else (None, None)
        cells = _product_cells(index, product) if product is not None else []
        gold_cells = [c for c in gold["cells"] if c["statement_id"] == g_statement["id"]]
        problems = (product["problems"] if product else []) + document_problems
        generic = any(GENERIC in problem for problem in problems)
        outcome: list[tuple[str | None, dict | None]] = []
        for g in gold_cells:  # pass 1: same label and period
            match = next((c for c in cells if not c["used"] and c["key"] == label_key(g["label"])
                          and c["period"] == g["period"]), None)
            if match is None:
                outcome.append((None, None))
                continue
            match["used"] = True
            if g["value"] is None:
                outcome.append(("dash_filled", match))  # the print has "-": any value here is wrong
            else:
                outcome.append(("correct" if match["value"] == g["value"] else "value_wrong", match))
        for i, (g, (result, _)) in enumerate(zip(gold_cells, outcome)):  # pass 2: the gold value under another label
            if result is not None:
                continue
            if g["value"] is None:
                outcome[i] = ("dash", None)  # printed "-", nothing in the workbook: right, and not a gold cell
                continue
            match = next((c for c in cells if not c["used"] and c["period"] == g["period"] and c["value"] == g["value"]), None)
            if match:
                match["used"] = True
            outcome[i] = ("label_wrong", match) if match else ("missing", None)
        missing = {i for i, (result, _) in enumerate(outcome) if result == "missing"}
        pointed_at = covered(pointers(problems), gold_cells, missing)
        rows = []
        for i, (g, (result, match)) in enumerate(zip(gold_cells, outcome)):
            if result == "dash":
                continue
            entry = {"label": g["label"], "period": g["period"], "printed": g["printed"], "gold_value": g["value"],
                     "page": g["page"], "result": result}
            if match:
                entry.update(product_id=match["id"], product_label=match["label"], product_value=match["value"],
                             flagged=match["flagged"])
            else:
                entry.update(flagged=i in pointed_at, generic=generic)
            rows.append(entry)
        results.append({
            "statement_id": g_statement["id"], "statement": g_statement["title"], "page": g_statement["page"],
            "found": product is not None, "product_index": index, "rows": rows, "cells": cells,
            "extras": [_extra(c, product) for c in cells if not c["used"]],
            "sums_checked": product.get("sums_checked") if product else None,
            "sums_uncertain": product.get("sums_uncertain") if product else None,
            "problems": problems if product else ["재무제표를 찾지 못했다"]})
    # product statements no gold statement took: every value of theirs is outside the gold (a 자본변동표 has none)
    unmatched = [{"product_index": i, "statement": s["title"], "page": s["page"],
                  "extras": [_extra(c, s) for c in _product_cells(i, s)], "cells": _product_cells(i, s)}
                 for i, s in unused if s["rows"]]
    extra_ids = {x["id"] for part in results + unmatched for x in part["extras"]}
    verdicts = check_verdicts(extras, extra_ids, report_sha256)
    for part in results + unmatched:
        for x in part["extras"]:
            x["verdict"] = verdicts.get(x["id"])

    def extras_counts(part: dict) -> dict:
        unmarked = [x for x in part["extras"] if not x["flagged"]]
        return {"not_in_gold": len(part["extras"]), "extras_wrong_unmarked": sum(x["verdict"] == "wrong" for x in unmarked),
                "unjudged_extras": sum(x["verdict"] is None for x in unmarked)}

    statements = []
    for part in results:
        rows = part.pop("rows")
        cells = part.pop("cells")
        count = lambda result, flagged=None: sum(1 for r in rows if r["result"] == result
                                                 and (flagged is None or r["flagged"] == flagged))
        counts = extras_counts(part)
        statements.append({
            **{k: part[k] for k in ("statement_id", "statement", "page", "found", "product_index")},
            "gold_cells": sum(1 for r in rows if r["gold_value"] is not None), "product_cells": len(cells),
            "correct": count("correct"), "value_wrong": count("value_wrong"), "label_wrong": count("label_wrong"),
            "missing": count("missing"), "dash_filled": count("dash_filled"),
            "S1": count("value_wrong", False) + count("dash_filled", False) + counts["extras_wrong_unmarked"],
            "L1": count("label_wrong", False), "S2": count("missing", False),
            "G1": sum(1 for r in rows if r["result"] == "missing" and not r["flagged"] and r.get("generic")),
            "flagged": sum(c["flagged"] for c in cells), **counts,
            "sums_checked": part["sums_checked"], "sums_uncertain": part["sums_uncertain"],
            "problems": part["problems"], "extras": part["extras"],
            "cells": [r for r in rows if r["result"] != "correct"]})
    others = []
    for part in unmatched:
        counts = extras_counts(part)
        others.append({k: part[k] for k in ("product_index", "statement", "page")} | counts
                      | {"S1": counts["extras_wrong_unmarked"], "flagged": sum(c["flagged"] for c in part["cells"]),
                         "product_cells": len(part["cells"]), "extras": part["extras"]})
    keys = ("gold_cells", "correct", "value_wrong", "label_wrong", "missing", "dash_filled", "S2", "L1", "G1")
    totals = {key: sum(s[key] for s in statements) for key in keys}
    for key in ("product_cells", "flagged", "not_in_gold", "unjudged_extras", "extras_wrong_unmarked", "S1"):
        totals[key] = sum(s[key] for s in statements + others)
    totals["S1_parts"] = {"value_wrong_unmarked": sum(sum(1 for c in s["cells"] if c["result"] == "value_wrong"
                                                          and not c["flagged"]) for s in statements),
                          "dash_filled_unmarked": sum(sum(1 for c in s["cells"] if c["result"] == "dash_filled"
                                                          and not c["flagged"]) for s in statements),
                          "extras_wrong_unmarked": totals["extras_wrong_unmarked"]}
    totals["statements_not_found"] = sum(not s["found"] for s in statements)
    totals["product_statements_not_in_gold"] = [s["statement"] for s in others]
    found = [s for s in statements if s["found"]]
    totals["sums_checked"] = sum(s["sums_checked"] or 0 for s in found)
    totals["statements_with_uncertain_sums"] = sum(1 for s in found if s["sums_uncertain"])
    # 0: the product checks this kind but could check no sum; None: it does not check this kind (income statements)
    totals["statements_without_sums"] = sum(1 for s in found if s["sums_checked"] == 0)
    totals["statements_sums_not_checked_by_kind"] = sum(1 for s in found if s["sums_checked"] is None)
    # a person confirms the mapping file even when the gold has no item to decide: a draft is never official
    mapping = gold.get("mapping") or {}
    mapping_confirmed = mapping.get("status") == "confirmed" and bool(mapping.get("confirmed_by"))
    extras_judged = totals["unjudged_extras"] == 0
    totals["status"] = {"machine_scored": True, "mapping_confirmed": mapping_confirmed, "extras_judged": extras_judged,
                        "report_saved": report_sha256 is not None,
                        "official_ready": mapping_confirmed and extras_judged and report_sha256 is not None}
    return {"report_sha256": report_sha256, "totals": totals, "statements": statements,
            "product_statements_not_in_gold": others}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, help="run the product on this PDF and save its report to --report")
    parser.add_argument("--report", type=Path, required=True, help="the product's saved report (API format)")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, help="the decisions for the gold's mapping items")
    parser.add_argument("--extras", type=Path, help="a person's verdicts on cells of --report outside the gold")
    parser.add_argument("--reader", choices=("rules", "ai"), default="ai")
    parser.add_argument("--page-map", type=Path, help="a synthetic scan's map (eval/d4_scan.py): renumber the gold")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {"decisions": {}}
    try:
        gold = apply_mapping(gold, mapping)
    except ValueError as exc:
        print(f"the gold is not confirmed: {exc}")
        return 2
    if args.page_map:
        from eval.d4_scan import scan_gold
        gold = scan_gold(gold, json.loads(args.page_map.read_text(encoding="utf-8")))
    if args.pdf:
        if args.report.exists():
            print(f"{args.report} exists: a saved report is never overwritten (verdicts may name its cells)")
            return 2
        from dart_review.documents import extract
        from dart_review.server import report
        extraction = extract(args.pdf, ocr="auto", reader=args.reader)
        data = report(extraction, args.pdf.name, args.reader)
        args.report.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    data = json.loads(args.report.read_text(encoding="utf-8"))
    extras = json.loads(args.extras.read_text(encoding="utf-8")) if args.extras else {}
    try:
        result = score(gold, data, extras, sha256(args.report))
    except ValueError as exc:
        print(f"the verdicts are not valid: {exc}")
        return 2
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
