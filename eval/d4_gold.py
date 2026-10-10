"""D4 gold builder (contract 4.2): the printed statement cells of a text PDF, checked against OpenDART.

    python eval/d4_gold.py --pdf report.pdf --corp-code 00126380 --out gold.json

It does not use the product's table code (dart_review/documents/): it reads the PDF's words with pdfplumber and
parses them with its own small rules, so a bug of the product's reader is not copied into the answer key. What
it cannot decide goes to the mapping table (``needs_mapping``) for a person, before the product is run:
- a printed amount line with more than two amount slots (which slot is which period is not known)
- a printed cell whose value OpenDART does not have in that statement and period (OpenDART groups some
  details differently; the printed value is the answer, but a person confirms it is printed so)
- a line with amounts but no label (a label wrapped onto the line above is taken when it touches)
- an OpenDART item found nowhere in the printed statement ("dart_only")

A cell is (statement, page, printed label, period); its value is the printed amount (parentheses negative)
in 원. Statements: from a title line followed by a dated period line, until the next title or the notes
heading. 자본변동표 is skipped (the product does not read it).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TITLE = re.compile(r"^(?:\d{1,2}\.|[ⅠⅡⅢⅣⅤ]+\.)?(연결|별도)?(재무상태표|대차대조표|포괄손익계산서|손익계산서|현금흐름표|자본변동표|"
                   r"이익잉여금처분계산서|결손금처리계산서)$")
KIND = {"재무상태표": "BS", "대차대조표": "BS", "포괄손익계산서": "CIS", "손익계산서": "IS", "현금흐름표": "CF",
        "자본변동표": "SCE", "이익잉여금처분계산서": "RE", "결손금처리계산서": "RE"}
DATED = re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일\s*(부터|현재|까지)")
UNIT = re.compile(r"단위\s*[:：]?\s*(백만\s*원|천\s*원|억\s*원|원)")
UNITS = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}
NOTES = re.compile(r"^(\(?연결\)?)?(재무제표에대한)?주석$")
GROUPED = re.compile(r"^\(?[-−△]?\d{1,3}(,\d{3})+\)?$")
SMALL = re.compile(r"^\(?[-−△]?\d{1,3}\)?$")
DASH = re.compile(r"^[-–—]$")
# item markers; a text layer may give Roman Ⅰ as "l" or "I" ("l. 유동자산")
MARKER = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVXlI|]{1,4}\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*")
NOTE_TAIL = re.compile(r"\s*\(\s*주\s*석?\s*[\d,\s]*\)?\s*$")  # "(주석 38)", or "(주석" with "38)" apart
UNIT_TEXT = re.compile(r"\(?\s*단\s*위\s*[:：]?\s*[천백만억]*\s*원\s*\)?")


def lines_of(path: Path) -> list[dict]:
    """Words grouped into lines (same top within 3 points), page by page, left to right."""
    import pdfplumber
    lines = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            words = sorted(page.extract_words(), key=lambda w: (round(w["top"]), w["x0"]))
            for word in words:
                word["page_height"] = page.height
            current: list[dict] = []
            for word in words:
                if current and abs(word["top"] - current[0]["top"]) > 3:
                    lines.append({"page": number, "words": sorted(current, key=lambda w: w["x0"])})
                    current = []
                current.append(word)
            if current:
                lines.append({"page": number, "words": sorted(current, key=lambda w: w["x0"])})
    for line in lines:
        line["text"] = " ".join(w["text"] for w in line["words"])
        line["compact"] = re.sub(r"\s+", "", line["text"])
        line["top"] = min(w["top"] for w in line["words"])
        line["bottom"] = max(w["bottom"] for w in line["words"])
    return lines


def statements_of(lines: list[dict]) -> list[dict]:
    """Statement blocks: a title with a dated line within the next four lines, until the next title or notes."""
    blocks, current = [], None
    for index, line in enumerate(lines):
        title = TITLE.match(line["compact"])
        following = [other["text"] for other in lines[index + 1:index + 5] if other["page"] == line["page"]]
        if title and any(DATED.search(text) for text in following):
            unit_text = next((m.group(1).replace(" ", "") for text in following + [l["text"] for l in lines[index + 5:index + 8]]
                              if (m := UNIT.search(text))), None)
            current = {"kind": KIND[title.group(2)], "title": (title.group(1) or "") + title.group(2),
                       "consolidated": title.group(1) == "연결", "page": line["page"], "unit_text": unit_text,
                       "lines": []}
            blocks.append(current)
            continue
        earlier_amounts = any(GROUPED.match(w["text"]) for other in lines[max(0, index - 60):index]
                              if other["page"] == line["page"] for w in other["words"])
        if NOTES.match(line["compact"]) and not earlier_amounts:
            current = None
            continue
        if current is not None:
            current["lines"].append(line)
    return [block for block in blocks if block["kind"] != "SCE"]


HEADER = re.compile(r"제\s*\d+\s*(\(\s*[당전]\s*\))?\s*기|과\s*목|구\s*분|당\s*기|전\s*기")
FOOTER = re.compile(r"^-\s*\d+\s*-$|Page\s*\d+|dart\.fss\.or\.kr|^Part\s*\d|BUSINESS\s+REPORT")


def _furniture_or_header(line: dict) -> bool:
    """A page header or footer, a period heading, a column heading, a dated or unit line: not a row. A line
    with a grouped amount is always a row."""
    if any(GROUPED.match(w["text"]) for w in line["words"]):
        return False
    text = line["text"]
    near_bottom = line["top"] > 0.92 * line["words"][0]["page_height"]
    return bool(near_bottom or FOOTER.search(text) or DATED.search(text) or UNIT.search(text)
                or (HEADER.search(text) and not re.search(r"주당", text)))


def value_of(printed: str, unit: int) -> int:
    text = printed.replace("−", "-").replace("△", "-")
    negative = text.startswith("(") or text.startswith("-")
    digits = int(re.sub(r"\D", "", text))
    return -digits * unit if negative else digits * unit


def clean(label: str) -> str:
    label = UNIT_TEXT.sub("", label)
    label = NOTE_TAIL.sub("", label).strip()
    label = MARKER.sub("", label)
    return re.sub(r"\s+", " ", label).strip()


def cells_of(block: dict, needs: list[dict]) -> list[dict]:
    unit = UNITS.get(block["unit_text"] or "", None)
    if unit is None:
        needs.append({"why": "no_unit", "statement": block["title"], "page": block["page"]})
        return []
    lines = block["lines"]
    grouped = [w for line in lines for w in line["words"] if GROUPED.match(w["text"])]
    if not grouped:
        return []
    zone = min(w["x0"] for w in grouped) - 2  # notes and labels are left of the amounts
    # the boundary between the two periods: between the right edges of first slots and left edges of second slots
    firsts, seconds = [], []
    slotted = []
    for line in lines:
        slots = [w for w in line["words"] if w["x0"] >= zone and (GROUPED.match(w["text"]) or SMALL.match(w["text"])
                                                                   or DASH.match(w["text"]) or w["text"] == "원")]
        slots = [w for w in slots if w["text"] != "원"]
        slotted.append(slots)
        if len(slots) == 2:
            firsts.append(slots[0]["x1"])
            seconds.append(slots[1]["x0"])
    boundary = (max(firsts) + min(seconds)) / 2 if firsts and seconds and max(firsts) < min(seconds) else None
    def label_of(line: dict) -> str:
        left = [w for w in line["words"] if w["x1"] <= zone + 2]
        if (len(left) >= 2 and re.fullmatch(r"[가-힣]{1,4}", left[0]["text"]) and MARKER.match(left[1]["text"] + " ")
                and left[1]["x0"] - left[0]["x1"] > 8):
            left = left[1:]  # a section word in its own column ("자산" beside "1. 장기매출채권")
        return clean(" ".join(w["text"] for w in left if re.search(r"[가-힣A-Za-z]", w["text"])))

    cells, previous_label_line = [], None
    for index, (line, slots) in enumerate(zip(lines, slotted)):
        if _furniture_or_header(line):
            continue
        label = label_of(line)
        if not slots:
            previous_label_line = line if label else None
            continue
        source = "auto"
        if not label and previous_label_line is not None and line["top"] - previous_label_line["bottom"] <= 4:
            # a label wrapped around its amounts: the touching label-only lines above and below, joined as written
            label, source = label_of(previous_label_line), "auto_wrapped"
            following = lines[index + 1] if index + 1 < len(lines) else None
            if (following is not None and not slotted[index + 1] and following["page"] == line["page"]
                    and following["top"] - line["bottom"] <= 4):
                label += label_of(following)
        if not re.search(r"[가-힣A-Za-z]", label):
            needs.append({"why": "no_label", "statement": block["title"], "page": line["page"], "line": line["text"]})
            continue
        # per-share rows and amounts followed by "원" are in 원 ("매 출 원 가" printed letter-spaced has a word "원" too,
        # so only a "원" among the amounts counts)
        suffix = any(w["text"] == "원" and w["x0"] >= zone for w in line["words"])
        row_unit = 1 if re.search(r"주당|단위\s*[:：]?\s*원", label) or suffix else unit
        amounts = [w for w in slots if not DASH.match(w["text"])]
        if len(slots) > 2:
            needs.append({"why": "slots", "statement": block["title"], "page": line["page"], "line": line["text"]})
            continue
        for position, word in enumerate(slots):
            if DASH.match(word["text"]):
                continue
            if len(slots) == 2:
                period = position
            elif boundary is not None:
                period = 0 if word["x1"] <= boundary else 1
            else:
                needs.append({"why": "one_slot_no_boundary", "statement": block["title"], "page": line["page"],
                              "line": line["text"]})
                continue
            cells.append({"statement": block["title"], "kind": block["kind"], "page": line["page"], "label": label,
                          "period": period, "printed": word["text"], "value": value_of(word["text"], row_unit),
                          "source": source})
        previous_label_line = None
        del amounts
    return cells


def build(path: Path, items_by_division: dict[str, list[dict]]) -> dict:
    lines = lines_of(path)
    needs: list[dict] = []
    statements, cells = [], []
    for block in statements_of(lines):
        statements.append({k: block[k] for k in ("kind", "title", "consolidated", "page", "unit_text")})
        cells += cells_of(block, needs)
    dart_only = []
    for statement in statements:
        if statement["kind"] == "RE":
            continue  # OpenDART has no 처분계산서: its cells are confirmed by a person from the print
        division = "CFS" if statement["consolidated"] or not statement["title"].startswith("별도") else "OFS"
        items = items_by_division.get(division, [])
        present = {item["sj_div"] for item in items}
        kind = statement["kind"] if statement["kind"] in present else {"IS": "CIS", "CIS": "IS"}.get(statement["kind"])
        mine = [c for c in cells if c["statement"] == statement["title"] and c["page"] >= statement["page"]]
        pool = [{"name": item["account_nm"], "period": period, "value": int(text.replace(",", ""))}
                for item in items if item["sj_div"] == kind
                for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount"))
                if re.fullmatch(r"-?[\d,]+", (text := (item.get(field) or "").strip())) and int(text.replace(",", ""))]
        for cell in mine:
            match = next((e for e in pool if e["period"] == cell["period"] and abs(e["value"]) == abs(cell["value"])), None)
            cell["dart"] = match["name"] if match else None
            if match is None:
                needs.append({"why": "not_in_dart", "statement": cell["statement"], "page": cell["page"],
                              "label": cell["label"], "period": cell["period"], "printed": cell["printed"]})
        printed = {(c["period"], abs(c["value"])) for c in mine}
        for entry in pool:
            if (entry["period"], abs(entry["value"])) not in printed:
                dart_only.append({"statement": statement["title"], "name": entry["name"], "period": entry["period"],
                                  "value": entry["value"]})
                needs.append({"why": "dart_only", "statement": statement["title"], "name": entry["name"],
                              "period": entry["period"], "value": entry["value"]})
    return {"statements": statements, "cells": cells, "needs_mapping": needs}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--corp-code", required=True)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--cache", type=Path, default=ROOT / "cache")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    from dart_review.cache import ResponseCache
    from dart_review.client import DartClient, NotCached
    client = DartClient(ResponseCache(args.cache), offline=True)
    items = {}
    for division in ("CFS", "OFS"):
        try:
            items[division] = client.financial_statements(args.corp_code, args.year, "11011", division).json().get("list", [])
        except NotCached:
            items[division] = []
    gold = build(args.pdf, items)
    args.out.write_text(json.dumps(gold, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(gold['statements'])} statements, {len(gold['cells'])} cells, {len(gold['needs_mapping'])} to map")
    return 0


if __name__ == "__main__":
    sys.exit(main())
