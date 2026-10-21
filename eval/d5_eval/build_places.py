"""D5 registered places for the position check (D4 contract 4.6, D5 contract 6판 2절): the frozen builder, place by
place, and a wrapped-label fallback for the places it cannot read.

    python eval/d5_eval/build_places.py --pdf-dir ~/Desktop/D5 --out eval/d5_eval/duplicate_places.json
    python eval/d5_eval/build_places.py --pdf-dir ~/Desktop/D5 --check eval/d5_eval/duplicate_places.json

``eval/d4_eval/position_check.py build`` (frozen in T) finds a place's printed rows by a line whose own words are the
label. A label printed over two lines around its amounts ("기타포괄손익-공정가치측정 금융자" / amounts / "산", 차바이오텍
8쪽) has no such line, so the builder stops for the whole document. This script runs the frozen builder on each place
alone (its own code, ``places_of`` narrowed to that place) and, only where it raises "0 printed lines of that label",
builds the place itself: a row is a line of the page with no letters whose period column (the frozen rule: amounts
counted from the right) prints a gold cell of the place, and whose neighbouring lines (the one above and the one
below, without amounts) join into the label. Every fallback place is listed in the output's ``fallback`` with its
lines, and the whole file must pass the frozen ``fits_gold`` against each document's gold. The tool files are not
changed; ``position_check.py verify`` cannot rebuild a fallback place, so ``--check`` rebuilds and compares instead.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

import position_check as pc  # noqa: E402
from eval.d4_gold import apply_mapping  # noqa: E402

DOCUMENTS = ROOT / "eval" / "d5_eval" / "documents.json"


def _fallback(document: dict, place: tuple, cells: list[dict], lines: list[dict]) -> dict:
    import d4_gold
    statement_id, key, period = place
    columns = pc.COLUMNS.get((document["key"], statement_id), 2)
    rows, evidence = [], []
    for page in sorted({c["page"] for c in cells}):
        here = [c for c in cells if c["page"] == page]
        on_page = [l for l in lines if l["page"] == page]
        for i, line in enumerate(on_page):
            label, amounts = pc._line_parts(line)
            if label or len(amounts) < columns or i == 0 or i + 1 >= len(on_page):
                continue
            above, below = pc._line_parts(on_page[i - 1]), pc._line_parts(on_page[i + 1])
            if above[1] or below[1] or pc.label_key(d4_gold.clean(above[0] + below[0])) != key:
                continue
            text = amounts[len(amounts) - columns + period]
            fit = next((c for c in here if pc._norm(c["printed"]) == pc._norm(text)), None)
            if fit is None:
                raise ValueError(f"{document['key']} {place}: line at {page}/{line['top']:.0f} prints {text!r}, no gold cell")
            here.remove(fit)
            top = round(line["words"][0]["top"], 1)
            rows.append({"page": page, "top": top, "label": fit["label"], "printed": fit["printed"], "value": fit["value"]})
            evidence.append(f"{page}/{top}: '{on_page[i - 1]['text']}' + '{line['text']}' + '{on_page[i + 1]['text']}'")
        if here:
            raise ValueError(f"{document['key']} {place}: page {page} gold cells without a printed row: {here}")
    return {"id": pc.place_id(statement_id, key, period), "statement_id": statement_id, "key": key, "period": period,
            "rows": rows}, evidence


def build(documents: dict, pdf_dir: Path) -> dict:
    import d4_gold
    out = {"note": ("Places with two or more gold cells, in print order (D4 contract 4.6); the frozen builder place by "
                    "place, and the wrapped-label fallback of eval/d5_eval/build_places.py where it cannot read a label "
                    "(listed in 'fallback')."), "documents": {}, "fallback": []}
    narrowed = pc.places_of
    try:
        for document in documents["documents"]:
            gold = apply_mapping(json.loads((ROOT / document["gold"]).read_text(encoding="utf-8")),
                                 json.loads((ROOT / document["mapping"]).read_text(encoding="utf-8")))
            lines = d4_gold.lines_of(pdf_dir / document["pdf"])
            places = []
            for place, cells in sorted(narrowed(gold).items(), key=lambda kv: (min(c["page"] for c in kv[1]), kv[0])):
                pc.places_of = lambda g, place=place, cells=cells: {place: cells}
                try:
                    built = pc.build({"documents": [document]}, pdf_dir)
                    places += built["documents"][document["key"]]["places"]
                except ValueError as exc:
                    if "0 printed lines of that label" not in str(exc):
                        raise
                    entry, evidence = _fallback(document, place, cells, lines)
                    places.append(entry)
                    out["fallback"].append({"document": document["key"], "place": entry["id"], "builder": str(exc),
                                            "lines": evidence})
            pc.places_of = narrowed
            entry = {"pdf_sha256": document["sha256"], "places": places}
            pc.fits_gold(entry, gold)  # the frozen check the aggregation applies
            out["documents"][document["key"]] = entry
    finally:
        pc.places_of = narrowed
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf-dir", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", type=Path)
    group.add_argument("--check", type=Path)
    args = parser.parse_args(argv)
    built = build(json.loads(DOCUMENTS.read_text(encoding="utf-8")), args.pdf_dir.expanduser())
    count = sum(len(d["places"]) for d in built["documents"].values())
    if args.check:
        registered = json.loads(args.check.read_text(encoding="utf-8"))
        if registered != built:
            print(f"NOT the same as {args.check}")
            return 1
        print(f"the same: {count} places ({len(built['fallback'])} by the wrapped-label fallback)")
        return 0
    if args.out.exists():
        parser.error(f"{args.out} exists")
    args.out.write_text(json.dumps(built, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{count} places of {len(built['documents'])} documents; {len(built['fallback'])} by the wrapped-label fallback")
    return 0


if __name__ == "__main__":
    sys.exit(main())
