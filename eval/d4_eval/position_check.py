"""D4 position check (contract 7판 4.6): rows that share a label in one statement, checked by their order.

    python eval/d4_eval/position_check.py build --pdf-dir ~/Desktop/D4 --out eval/d4_eval/duplicate_places.json
    python eval/d4_eval/position_check.py verify --pdf-dir ~/Desktop/D4      # the registered file, built again: same?
    python eval/d4_eval/position_check.py check --key 05_00117212 --report <report.json> [--page-map <map.json>] \
        [--verdicts <verdicts.json>] --out <position.json>

Why: the frozen scorer (eval/d4_score.py) pairs a gold cell with a product cell of the same label, period, and
value. When a label is printed on two rows of one statement (두산 10쪽: 유동 "파생상품평가자산 204,454" and 비유동
"파생상품평가자산 54,102"; 10쪽 유동 "충당부채" and 11쪽 비유동 "충당부채"), a workbook that swaps the two values is
scored correct on both (Codex seventh review 1; the scorer takes a cell of the gold's page first, else any page).
The scorer stays frozen; this check runs on the same saved report and adds what it misses.

``build`` (before registration): for every place (statement, label as the scorer compares it, period) with two or
more gold cells, find each cell's printed line in the PDF's text layer (the line's label and the printed text in
that period's column, on the cell's page) and record the cells in print order: by page, then top to bottom. A place
whose lines cannot all be found stops the build: it is resolved by hand before registration, never guessed.
``verify`` builds them again from the PDFs and the mappings as they are now and compares the result with the
registered file: after the mappings are confirmed, and before registration, it must say they are the same (Codex
seventh re-check 3).

``check`` (after the run): the gold as the scorer has it (mapping applied, scan pages renumbered), the product
statement as the scorer finds it (same title, first page in range, first unused, gold statements in order, 자본변동표
skipped). For each place, the product rows of that label (with any value) in the statement, in report order:
- as many rows as printed rows: row k is compared with printed row k. A row whose value is not printed row k's (also
  a value where row k printed "-") is wrong; ``wrong_unmarked`` counts those without "확인 필요". The scorer may have
  counted some of these cells already (a value no printed row has is "value wrong" there, and so is a second copy of
  one printed value), or a cell of the place that is right by order: the place adds only what the scorer missed,
  ``added`` = max(0, wrong_unmarked - the scorer's unmarked "value wrong" and "dash filled" cells of the place).
  So S1 + S1_position never counts a cell twice and never falls below the scorer's S1.
- another number of rows (a row lost, split, or added): the rows cannot be paired by order. When a printed value
  of the place stands in any row of that label and period in the statement and the place's printed rows differ, a
  person decides ("needs_verdict"; ``--verdicts`` gives "ok" or "wrong" and a note, by place id, for the report's
  SHA-256). A "wrong" verdict's ``wrong_unmarked`` counts only cells the scorer scored "correct" that stand in another
  printed row's place without "확인 필요": the result lists each row with the scorer's result for its cell, and the
  count may not exceed those cells. Cells the scorer counted wrong are in S1 already, and cells outside the gold are
  judged by 4.5. Otherwise no printed value can stand in a wrong row ("not_pairable_no_swap").
A verdict is an object: "wrong" needs an explicit whole number ``wrong_unmarked`` (0 too, when every wrong cell is
marked), "ok" takes none or 0 (Codex seventh re-check 2).
The result says ``position_ready`` only when no place waits for a verdict. Each check first compares the registered
places with the places of the gold it scores (the mapping as it is now): another set of places, or other printed
cells in a place, refuses the check, so a changed mapping cannot leave a place unchecked.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from eval.d4_gold import apply_mapping, label_key  # noqa: E402
from eval.d4_score import score  # noqa: E402

DOCUMENTS = ROOT / "eval" / "d4_eval" / "documents.json"
AMOUNT = re.compile(r"^\(?[-−△]?\d{1,3}(,\d{3})*\)?$|^[-–—]$")
LETTERS = re.compile(r"[가-힣A-Za-z]")
# period columns of a statement, counted from the right of a printed line (note numbers stand left of the amounts):
# two (당기, 전기), and three where a balance sheet also prints 전기초 (쌍용씨앤이, contract 10 ⑥)
COLUMNS = {("11_00138224", "연결재무상태표@8"): 3}


def place_id(statement_id: str, key: str, period: int) -> str:
    return f"{statement_id}|{key}|{period}"


def places_of(gold: dict) -> dict[tuple, list[dict]]:
    """Places (statement, label key, period) holding two or more gold cells (printed or "-"), with at least one
    printed amount."""
    found: dict[tuple, list[dict]] = defaultdict(list)
    for cell in gold["cells"]:
        found[(cell["statement_id"], label_key(cell["label"]), cell["period"])].append(cell)
    return {k: v for k, v in found.items() if len(v) > 1 and any(c["value"] is not None for c in v)}


def _norm(printed: str) -> str:
    return re.sub(r"[\s,]", "", printed.replace("−", "-").replace("–", "-").replace("—", "-"))


def _line_parts(line: dict) -> tuple[str, list[str]]:
    """A text line's label (words with letters) and its amounts (left to right)."""
    words = line["words"]
    label = " ".join(w["text"] for w in words if LETTERS.search(w["text"]))
    amounts = [w["text"] for w in words if AMOUNT.match(w["text"]) and not LETTERS.search(w["text"])]
    return label, amounts


def build(documents: dict, pdf_dir: Path) -> dict:
    import d4_gold
    out = {"note": "Places with two or more gold cells, in print order (contract 7판 4.6); built before registration.",
           "documents": {}}
    for document in documents["documents"]:
        gold = apply_mapping(json.loads((ROOT / document["gold"]).read_text(encoding="utf-8")),
                             json.loads((ROOT / document["mapping"]).read_text(encoding="utf-8")))
        lines = d4_gold.lines_of(pdf_dir / document["pdf"])
        places = []
        for (statement_id, key, period), cells in sorted(places_of(gold).items(),
                                                         key=lambda kv: (min(c["page"] for c in kv[1]), kv[0])):
            name = f"{document['key']} {place_id(statement_id, key, period)}"
            columns = COLUMNS.get((document["key"], statement_id), 2)
            ordered = []
            for page in sorted({c["page"] for c in cells}):
                here = [c for c in cells if c["page"] == page]
                candidates = [(round(l["words"][0]["top"], 1), *_line_parts(l)) for l in lines if l["page"] == page]
                rows = [(top, amounts) for top, label, amounts in candidates if label_key(d4_gold.clean(label)) == key]
                if len(rows) != len(here):
                    raise ValueError(f"{name}: page {page} has {len(here)} gold cells, {len(rows)} printed lines of that label")
                for top, amounts in rows:  # each printed line takes the gold cell whose printed text is in its period column
                    if len(amounts) < columns:
                        raise ValueError(f"{name}: line at {page}/{top} has {len(amounts)} amounts, fewer than {columns} columns")
                    text = amounts[len(amounts) - columns + period]
                    fit = next((c for c in here if _norm(c["printed"]) == _norm(text)), None)
                    if fit is None:
                        raise ValueError(f"{name}: line at {page}/{top} prints {text!r}, no gold cell of the place has it")
                    here.remove(fit)
                    ordered.append({"page": page, "top": top, "label": fit["label"], "printed": fit["printed"],
                                    "value": fit["value"]})
            places.append({"id": place_id(statement_id, key, period), "statement_id": statement_id, "key": key,
                           "period": period, "rows": ordered})
        out["documents"][document["key"]] = {"pdf_sha256": document["sha256"], "places": places}
    return out


def _cells_by_place(places: dict[tuple, list[dict]]) -> dict[str, list[tuple]]:
    return {place_id(*k): sorted(((c["page"], c["printed"], c["value"]) for c in v), key=repr) for k, v in places.items()}


def fits_gold(entry: dict, gold: dict) -> None:
    """ValueError unless the registered places are the places of this gold (the text PDF's: original pages), each
    with the same printed cells (page, printed text, value)."""
    expected = _cells_by_place(places_of(gold))
    found = {place["id"]: sorted(((r["page"], r["printed"], r["value"]) for r in place["rows"]), key=repr)
             for place in entry["places"]}
    if len(found) != len(entry["places"]):
        raise ValueError("the registered places list a place twice")
    missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
    changed = sorted(k for k in set(expected) & set(found) if expected[k] != found[k])
    if missing or extra or changed:
        raise ValueError(f"the registered places do not fit the gold with its mapping as it is now (missing "
                         f"{missing[:3]}, not in the gold {extra[:3]}, other cells {changed[:3]}): build them again "
                         f"before registration")


def _verdict_count(name: str, verdict: object) -> int:
    """The unmarked wrong cells a person's verdict on a place counts; ValueError unless it is well formed."""
    form = '{"verdict": "wrong", "wrong_unmarked": n, "note": ...} or {"verdict": "ok", "note": ...}'
    if not isinstance(verdict, dict) or verdict.get("verdict") not in ("ok", "wrong") \
            or not isinstance(verdict.get("note"), str) or not verdict["note"].strip():
        raise ValueError(f"{name}: a verdict is {form}, not {verdict!r}")
    count = verdict.get("wrong_unmarked")
    whole = isinstance(count, int) and not isinstance(count, bool) and count >= 0
    if verdict["verdict"] == "wrong" and not whole:
        raise ValueError(f"{name}: a \"wrong\" verdict says how many unmarked cells are wrong (wrong_unmarked, 0 or "
                         f"more), not {count!r}")
    if verdict["verdict"] == "ok" and "wrong_unmarked" in verdict and not (whole and count == 0):
        raise ValueError(f"{name}: an \"ok\" verdict counts no wrong cell, not wrong_unmarked {count!r}")
    return count if verdict["verdict"] == "wrong" else 0


def _gold_for(document: dict, page_map: dict | None) -> dict:
    gold = apply_mapping(json.loads((ROOT / document["gold"]).read_text(encoding="utf-8")),
                         json.loads((ROOT / document["mapping"]).read_text(encoding="utf-8")))
    if page_map:
        from eval.d4_scan import scan_gold
        gold = scan_gold(gold, page_map)
    return gold


def _statement_pairs(gold: dict, report: dict) -> dict[str, dict | None]:
    """The product statement the scorer pairs with each gold statement (eval/d4_score.py score())."""
    unused = list(enumerate(report["statements"]))
    pairs = {}
    for statement in gold["statements"]:
        if statement["kind"] == "SCE":
            continue
        first, last = statement["page"], statement.get("end_page", statement["page"])
        found = next(((i, s) for i, s in unused if s["title"] == statement["title"] and first <= s["page"] <= last), None)
        if found is not None:
            unused.remove(found)
        pairs[statement["id"]] = found
    return pairs


def check(registered: dict, document: dict, report: dict, page_map: dict | None = None, verdicts: dict | None = None,
          report_sha256: str | None = None) -> dict:
    gold = _gold_for(document, page_map)
    entry = registered["documents"].get(document["key"])
    if entry is None or entry.get("pdf_sha256") != document["sha256"]:
        raise ValueError("the registered places are of another PDF (or of no registered document)")
    fits_gold(entry, _gold_for(document, None) if page_map else gold)
    if report.get("source_sha256") != (gold.get("source") or {}).get("sha256"):
        raise ValueError("the report is of another PDF than the gold (source_sha256 differs)")
    pairs = _statement_pairs(gold, report)
    # the scorer's result for each product cell (by its id "statement/row/column"; a paired cell not listed is
    # "correct") and its unmarked "value wrong" and "dash filled" cells by place (it needs no verdicts for these)
    counted: dict[tuple, int] = defaultdict(int)
    scorer_result: dict[str, str] = {}
    for part in score(gold, report)["statements"]:
        for cell in part["cells"]:
            if cell.get("product_id"):
                scorer_result[cell["product_id"]] = cell["result"]
            if cell["result"] in ("value_wrong", "dash_filled") and not cell["flagged"]:
                counted[(part["statement_id"], label_key(cell["label"]), cell["period"])] += 1
        for extra in part["extras"]:
            scorer_result[extra["id"]] = "not_in_gold"
    verdicts = {} if verdicts is None else verdicts
    if not isinstance(verdicts, dict) or not isinstance(verdicts.get("verdicts") or {}, dict):
        raise ValueError('the position verdicts are {"report_sha256", "judged_by", "verdicts": {place id: verdict}}')
    given = verdicts.get("verdicts") or {}
    if given:
        if report_sha256 is not None and verdicts.get("report_sha256") != report_sha256:
            raise ValueError("the position verdicts are for another report (report_sha256 differs)")
        if not verdicts.get("judged_by"):
            raise ValueError("the position verdicts do not say who judged them (judged_by)")
    results, used_verdicts = [], set()
    for place in entry["places"]:
        pair = pairs.get(place["statement_id"])
        result = {"id": place["id"], "pages": sorted({r["page"] for r in place["rows"]}), "printed_rows": len(place["rows"])}
        if pair is None:
            results.append(result | {"status": "statement_not_found"})
            continue
        index, statement = pair
        rows = []
        for r_index, row in enumerate(statement["rows"]):
            if label_key(row["label"]) != place["key"] or not row["values"]:
                continue
            cell = next((v for v in row["values"] if v["column"] == place["period"]), None)
            has_value = cell is not None and cell["value"] is not None
            rows.append({"row": r_index, "value": cell["value"] if cell else None,
                         "flagged": bool(cell and cell.get("status") == "확인 필요"),
                         "scorer": scorer_result.get(f"{index}/{r_index}/{place['period']}", "correct") if has_value else None})
        printed = [r["value"] for r in place["rows"]]
        scorer = counted[(place["statement_id"], place["key"], place["period"])]
        result |= {"product_rows": len(rows), "scorer_wrong_unmarked": scorer}
        if len(rows) == len(printed):
            wrong = [k for k, (row, value) in enumerate(zip(rows, printed)) if row["value"] is not None and row["value"] != value]
            unmarked = sum(1 for k in wrong if not rows[k]["flagged"])
            result |= {"status": "position_wrong" if wrong else "in_order", "wrong_rows": wrong,
                       "wrong_unmarked": unmarked, "added": max(0, unmarked - scorer)}
            if wrong:
                result |= {"printed": printed, "rows": rows}
        else:
            # rows lost, split, or added: order cannot pair them. A printed value of the place in any row of this label
            # and period may stand in another printed row's place
            hits = sum(1 for row in statement["rows"] if label_key(row["label"]) == place["key"] for v in row["values"]
                       if v["column"] == place["period"] and v["value"] is not None and v["value"] in printed)
            if hits and len(set(printed)) > 1:
                verdict = given.get(place["id"])
                result |= {"status": "needs_verdict", "printed": printed, "rows": rows}
                if verdict is not None:
                    unmarked = _verdict_count(place["id"], verdict)
                    could = sum(1 for r in rows if r["scorer"] == "correct" and not r["flagged"])
                    if unmarked > could:
                        raise ValueError(f"{place['id']}: wrong_unmarked {unmarked} counts more than the {could} unmarked "
                                         f"cells the scorer scored correct (the others are in S1 or judged by 4.5)")
                    used_verdicts.add(place["id"])
                    result |= {"status": "judged", "verdict": verdict["verdict"], "wrong_unmarked": unmarked,
                               "added": unmarked}
            else:
                result["status"] = "not_pairable_no_swap"
        results.append(result)
    unknown = sorted(set(given) - used_verdicts)
    if unknown:
        raise ValueError(f"verdicts for {len(unknown)} place(s) that need none: {', '.join(unknown[:5])}")
    totals = {"places": len(results),
              "in_order": sum(r["status"] == "in_order" for r in results),
              "position_wrong": sum(len(r.get("wrong_rows", [])) for r in results),
              "S1_position": sum(r.get("added", 0) for r in results),
              "needs_verdict": sum(r["status"] == "needs_verdict" for r in results)}
    totals["position_ready"] = totals["needs_verdict"] == 0
    return {"key": document["key"], "report_sha256": report_sha256, "totals": totals, "places": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("build")
    make.add_argument("--pdf-dir", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    same = commands.add_parser("verify")
    same.add_argument("--pdf-dir", type=Path, required=True)
    same.add_argument("--registered", type=Path, default=ROOT / "eval" / "d4_eval" / "duplicate_places.json")
    test = commands.add_parser("check")
    test.add_argument("--key", required=True)
    test.add_argument("--report", type=Path, required=True)
    test.add_argument("--page-map", type=Path)
    test.add_argument("--verdicts", type=Path)
    test.add_argument("--registered", type=Path, default=ROOT / "eval" / "d4_eval" / "duplicate_places.json")
    test.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    documents = json.loads(DOCUMENTS.read_text(encoding="utf-8"))
    if args.command == "build":
        if args.out.exists():
            parser.error(f"{args.out} exists")
        result = build(documents, args.pdf_dir.expanduser())
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(sum(len(d["places"]) for d in result["documents"].values()), "places")
        return 0
    if args.command == "verify":
        registered = json.loads(args.registered.read_text(encoding="utf-8"))
        built = build(documents, args.pdf_dir.expanduser())
        differ = sorted(k for k in set(built["documents"]) | set(registered["documents"])
                        if built["documents"].get(k) != registered["documents"].get(k))
        count = sum(len(d["places"]) for d in built["documents"].values())
        if differ:
            print(f"NOT the same: {', '.join(differ)} differ from {args.registered}; build the places again")
            return 1
        print(f"the same: {count} places of {len(built['documents'])} documents, built again from the PDFs and the "
              f"mappings as they are now")
        return 0
    if args.out.exists():
        parser.error(f"{args.out} exists")
    document = next((d for d in documents["documents"] if d["key"] == args.key), None)
    if document is None:
        parser.error(f"{args.key} is not a registered document")
    page_map = json.loads(args.page_map.read_text(encoding="utf-8")) if args.page_map else None
    verdicts = json.loads(args.verdicts.read_text(encoding="utf-8")) if args.verdicts else None
    registered = json.loads(args.registered.read_text(encoding="utf-8"))
    report_sha256 = hashlib.sha256(args.report.read_bytes()).hexdigest()
    result = check(registered, document, json.loads(args.report.read_text(encoding="utf-8")), page_map, verdicts, report_sha256)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
