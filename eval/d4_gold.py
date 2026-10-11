"""D4 gold builder (contract 4.2): the printed statement cells of a text PDF, checked against OpenDART.

    python eval/d4_gold.py --pdf report.pdf --corp-code 00126380 --out gold.json

It does not use the product's table code (dart_review/documents/): it reads the PDF's words with pdfplumber and
parses them with its own small rules, so a bug of the product's reader is not copied into the answer key (both
read the same text layer, so a fault of that layer can still be shared).

Each statement has an id (title@first page) and a page range; each cell (statement id, page, printed label,
period) has the printed amount in 원 (parentheses negative), or None where the print has "-". What the builder
cannot decide is a mapping item (``needs_mapping``, each with an id) for a person, before the product is run:
- not_in_dart: a printed cell whose value OpenDART does not have in that statement and period (one to one)
- dart_only: an OpenDART value printed nowhere in the statement (a value printed on two rows counts twice)
- uncertain_line: a line near the page bottom without a grouped amount (a footer or a small-amount row), with
  its proposed cells; never dropped silently
- no_grouped_amounts: a statement without any amount printed with thousands separators (all amounts small,
  printed without separators, or none), with its lines that have numbers: the builder cannot place its columns
- ungrouped_amount: a line with a number of four or more digits printed without separators ("1000") in the amount
  area: never read as a cell automatically, never dropped
- statement_not_found: a consolidated statement OpenDART has (재무상태표, 손익계산서, 포괄손익계산서, 현금흐름표)
  that the builder found no block for. A person writes it ("add_statement": the statement and its cells), says
  that one printed 포괄손익계산서 is both 손익 and 포괄손익 ("same_statement", only when the other is printed), or
  takes the document out of the official verdict ("unscorable"); it is never just ignored, since the product
  could miss the same statement and nothing would be checked
- slots (more than two amounts on a line), no_label, one_slot_no_boundary, no_unit
A line is dropped without a person only when it is a known page footer, a dated period line, or nothing but
heading and unit words ("과 목", "제 57 (당) 기", "(단위: 원)"): a line with a row label of its own is never
dropped, so "당기순이익 47 48" or "기본주당이익(단위: 원) 47 48" is a row.
``apply_mapping`` takes the person's decisions and checks them; the scorer refuses a gold with an undecided item.
Statements run from a title followed by a dated period line to the next title or the notes heading. 자본변동표
is skipped (the product does not read it).
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
UNGROUPED = re.compile(r"^\(?[-−△]?\d{4,}\)?$")  # "1000": an amount without separators, or a year
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
            name = (title.group(1) or "") + title.group(2)
            current = {"id": f"{name}@{line['page']}", "kind": KIND[title.group(2)], "title": name,
                       "consolidated": title.group(1) == "연결", "page": line["page"], "end_page": line["page"],
                       "unit_text": unit_text, "lines": []}
            blocks.append(current)
            continue
        earlier_amounts = any(GROUPED.match(w["text"]) for other in lines[max(0, index - 60):index]
                              if other["page"] == line["page"] for w in other["words"])
        if NOTES.match(line["compact"]) and not earlier_amounts:
            current = None
            continue
        if current is not None:
            current["lines"].append(line)
            current["end_page"] = line["page"]
    return [block for block in blocks if block["kind"] != "SCE"]


# the words of a period or column heading ("과 목", "주 석", "제 57 (당) 기", "당기말"); a heading line has nothing else
HEADING = re.compile(r"제\s*\d+\s*(\(\s*[당전]\s*\))?\s*기\s*[말초]?|계\s*정\s*과\s*목|과\s*목|구\s*분|주\s*석|"
                     r"[당전]\s*기\s*[말초]?|금\s*액")
FOOTER = re.compile(r"^-\s*\d+\s*-$|Page\s*\d+|dart\.fss\.or\.kr|^Part\s*\d|BUSINESS\s+REPORT")
PAGE_NUMBER = re.compile(r"^[-–—]?\s*\d{1,3}\s*[-–—]?$")


def _is_heading(text: str) -> bool:
    """Nothing but heading and unit words: no label of a row is left ("당기순이익 47 48" leaves "순이익")."""
    return not re.search(r"[가-힣A-Za-z]", HEADING.sub("", UNIT_TEXT.sub("", text)))


def _line_kind(line: dict) -> str:
    """"row", "drop" (a known page footer, a dated period line, a heading or unit line, a lone page number at the
    page bottom), or "uncertain" (a line near the page bottom without a grouped amount: a footer or a small-amount
    row; a person decides, it is never dropped silently). A line with a grouped amount is always a row."""
    if any(GROUPED.match(w["text"]) for w in line["words"]):
        return "row"
    text = line["text"]
    if FOOTER.search(text) or DATED.search(text) or _is_heading(text) and re.search(r"[가-힣]", text):
        return "drop"
    if line["top"] > 0.92 * line["words"][0]["page_height"]:
        return "drop" if PAGE_NUMBER.match(text.strip()) else "uncertain"
    return "row"


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
    if not grouped:  # the amount columns are found from grouped amounts: a person decides this statement
        numbered = [line["text"] for line in lines if _line_kind(line) != "drop" and any(
                    SMALL.match(w["text"]) or UNGROUPED.match(w["text"]) or DASH.match(w["text"]) for w in line["words"])]
        if numbered:
            needs.append({"why": "no_grouped_amounts", "statement_id": block["id"], "statement": block["title"],
                          "page": block["page"], "lines": numbered})
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
        kind = _line_kind(line)
        if kind == "drop":
            continue
        label = label_of(line)
        if not slots and not any(w["x0"] >= zone and UNGROUPED.match(w["text"]) for w in line["words"]):
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
        previous_label_line = None
        where = {"statement_id": block["id"], "statement": block["title"], "page": line["page"], "line": line["text"]}
        if any(w["x0"] >= zone and UNGROUPED.match(w["text"]) for w in line["words"]):
            needs.append({"why": "ungrouped_amount", **where})  # its columns are not known: a person writes its cells
            continue
        if not re.search(r"[가-힣A-Za-z]", label):
            needs.append({"why": "no_label", **where})
            continue
        if len(slots) > 2:
            needs.append({"why": "slots", **where})
            continue
        # per-share rows and amounts followed by "원" are in 원 ("매 출 원 가" printed letter-spaced has a word "원" too,
        # so only a "원" among the amounts counts)
        suffix = any(w["text"] == "원" and w["x0"] >= zone for w in line["words"])
        row_unit = 1 if re.search(r"주당|단위\s*[:：]?\s*원", label) or suffix else unit
        found = []
        for position, word in enumerate(slots):
            if len(slots) == 2:
                period = position
            elif boundary is not None:
                period = 0 if word["x1"] <= boundary else 1
            else:
                needs.append({"why": "one_slot_no_boundary", **where})
                found = []
                break
            dash = bool(DASH.match(word["text"]))
            found.append({"statement_id": block["id"], "statement": block["title"], "kind": block["kind"],
                          "page": line["page"], "label": label, "period": period, "printed": word["text"],
                          "value": None if dash else value_of(word["text"], row_unit), "source": source})
        if kind == "uncertain":
            needs.append({"why": "uncertain_line", **where, "proposed": found})
            continue
        cells += found
    return cells


def build(path: Path, items_by_division: dict[str, list[dict]]) -> dict:
    import hashlib
    lines = lines_of(path)
    # the PDF the gold is of: a scan's page map and a saved product report are checked against it
    source = {"file": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None}
    needs: list[dict] = []
    statements, cells = [], []
    for block in statements_of(lines):
        statements.append({k: block[k] for k in ("id", "kind", "title", "consolidated", "page", "end_page", "unit_text")})
        cells += cells_of(block, needs)
    for statement in statements:
        if statement["kind"] == "RE":
            continue  # OpenDART has no 처분계산서: its cells stand on the print
        division = "OFS" if statement["title"].startswith("별도") else "CFS"
        items = items_by_division.get(division, [])
        present = {item["sj_div"] for item in items}
        kind = statement["kind"] if statement["kind"] in present else {"IS": "CIS", "CIS": "IS"}.get(statement["kind"])
        mine = [c for c in cells if c["statement_id"] == statement["id"] and c["value"] is not None]
        # OpenDART's values matched one to one with the printed cells (a value printed on two rows is two entries)
        pool = [{"name": item["account_nm"], "period": period, "value": int(text.replace(",", "")), "used": False}
                for item in items if item["sj_div"] == kind
                for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount"))
                if re.fullmatch(r"-?[\d,]+", (text := (item.get(field) or "").strip())) and int(text.replace(",", ""))]
        for cell in mine:
            match = next((e for e in pool if not e["used"] and e["period"] == cell["period"]
                          and abs(e["value"]) == abs(cell["value"])), None)
            cell["dart"] = match["name"] if match else None
            if match:
                match["used"] = True
            else:
                needs.append({"why": "not_in_dart", "statement_id": statement["id"], "statement": statement["title"],
                              "page": cell["page"], "label": cell["label"], "period": cell["period"],
                              "printed": cell["printed"]})
        for entry in pool:
            if not entry["used"]:
                needs.append({"why": "dart_only", "statement_id": statement["id"], "statement": statement["title"],
                              "name": entry["name"], "period": entry["period"], "value": entry["value"]})
    # a consolidated statement OpenDART has but no block was found for: never left without an item (손익 and 포괄손익
    # are looked for apart; a person says when one printed statement is both)
    printed = {s["kind"] for s in statements if s["consolidated"]}
    for kind in sorted({item["sj_div"] for item in items_by_division.get("CFS", [])} & {"BS", "IS", "CIS", "CF"} - printed):
        needs.append({"why": "statement_not_found", "division": "CFS", "kind": kind})
    for number, need in enumerate(needs, 1):
        need["id"] = f"n{number}"
    return {"source": source, "statements": statements, "cells": cells, "needs_mapping": needs}


def cell_key(cell: dict) -> str:
    return f"{cell['statement_id']}|{cell['page']}|{cell['label']}|{cell['period']}|{cell['printed']}"


ALLOWED = {"not_in_dart": {"keep", "drop"}, "dart_only": {"ignore", "add"}, "uncertain_line": {"ignore", "add"},
           "no_grouped_amounts": {"ignore", "add"}, "ungrouped_amount": {"ignore", "add"}, "slots": {"ignore", "add"},
           "no_label": {"ignore", "add"}, "one_slot_no_boundary": {"ignore", "add"}, "no_unit": {"ignore", "add"},
           "statement_not_found": {"add_statement", "same_statement", "unscorable"}}
STATEMENT_KEYS = ("id", "kind", "title", "consolidated", "page", "end_page", "unit_text")


def label_key(label: str) -> str:
    """A label as the scorer compares it: without spaces, a leading item marker, and a trailing note reference."""
    label = re.sub(r"\(\s*주\s*석?\s*[\d,\s]+\)\s*$", "", label or "")
    label = re.sub(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?|[IVXlI|]{1,4}\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*", "", label)
    return re.sub(r"\s+", "", label)


def _place(cell: dict) -> tuple:
    """Where a gold cell is printed, as the scorer tells cells apart: two gold cells at one place would be one
    printed row counted twice."""
    return cell["statement_id"], cell["page"], label_key(cell["label"]), cell["period"]


def _checked_cell(cell: object, statements: dict[str, dict], source: str) -> dict:
    """A cell a person adds: of a gold statement and a page in its range, a label, period 0 or 1, and the value its
    printed text gives (in 원: the printed number in the statement's unit, or in 원 for a per-share row (주당), with
    its sign; any unit only when the statement's unit is unknown; None for "-")."""
    if not isinstance(cell, dict):
        raise ValueError(f"{source}: a cell is an object, not {cell!r}")
    statement = statements.get(cell.get("statement_id"))
    if statement is None:
        raise ValueError(f"{source}: no gold statement {cell.get('statement_id')!r}")
    page, label, period, printed, value = (cell.get(k) for k in ("page", "label", "period", "printed", "value"))
    if not isinstance(page, int) or not statement["page"] <= page <= statement.get("end_page", statement["page"]):
        raise ValueError(f"{source}: page {page!r} is not in {statement['id']}")
    if not isinstance(label, str) or not re.search(r"[가-힣A-Za-z]", label):
        raise ValueError(f"{source}: label {label!r} is not a row label")
    if period not in (0, 1):
        raise ValueError(f"{source}: period {period!r} is not 0 or 1")
    if not isinstance(printed, str) or not (DASH.match(printed) or GROUPED.match(printed) or SMALL.match(printed)):
        raise ValueError(f"{source}: printed {printed!r} is not an amount or '-'")
    if DASH.match(printed):
        fits = value is None
    else:
        if statement.get("unit_text") in UNITS:
            units = {UNITS[statement["unit_text"]]} | ({1} if "주당" in label else set())
        else:
            units = set(UNITS.values())
        fits = isinstance(value, int) and not isinstance(value, bool) and any(
            value == value_of(printed, unit) for unit in units)
    if not fits:
        raise ValueError(f"{source}: value {value!r} is not what {printed!r} prints")
    return {"statement_id": statement["id"], "statement": statement["title"], "kind": statement["kind"], "page": page,
            "label": label, "period": period, "printed": printed, "value": value, "source": source}


def apply_mapping(gold: dict, mapping: dict) -> dict:
    """The gold with a person's decisions. ``mapping`` has a ``status`` ("draft", or "confirmed" with
    ``confirmed_by`` and ``confirmed_at``) and ``decisions``: one per ``needs_mapping`` item and no other, each with
    a ``note`` of its own (the page and printed text it rests on; two items never share a note):
    - "keep": the automatic cell stands (printed, OpenDART shows it otherwise)
    - "drop": the automatic cell is removed (``not_in_dart`` only)
    - "ignore": nothing changes (an OpenDART-only value not printed, a footer line)
    - "add": ``cells`` (or, for an ``uncertain_line``, its ``proposed`` cells when ``cells`` is absent) join the
      gold: at least one, each checked (``_checked_cell``), none at the place (statement, page, label as the scorer
      compares it, period) of another gold cell
    - for a ``statement_not_found``: "add_statement" (``statement`` with its id, kind, title, pages, and unit, and
      its ``cells``), "same_statement" (손익 or 포괄손익 when the other is printed: one statement shows both), or
      "unscorable" (the document gets no official verdict; the gold carries the reason)
    Raises ValueError; the scorer does not score a gold whose mapping does not pass. The returned gold carries the
    mapping's status for the scorer (only a confirmed mapping makes an official score)."""
    status = mapping.get("status")
    if status not in ("draft", "confirmed"):
        raise ValueError(f"mapping status {status!r} is not 'draft' or 'confirmed'")
    if status == "confirmed" and not (mapping.get("confirmed_by") and mapping.get("confirmed_at")):
        raise ValueError("a confirmed mapping names who confirmed it and when (confirmed_by, confirmed_at)")
    decisions = mapping.get("decisions", {})
    ids = {need["id"] for need in gold["needs_mapping"]}
    missing = [need["id"] for need in gold["needs_mapping"] if need["id"] not in decisions]
    if missing:
        raise ValueError(f"mapping has no decision for {len(missing)} item(s): {', '.join(missing[:10])}")
    unknown = sorted(set(decisions) - ids)
    if unknown:
        raise ValueError(f"mapping decides {len(unknown)} item(s) the gold does not have: {', '.join(unknown[:10])}")
    notes = [str(decisions[i].get("note") or "").strip() for i in sorted(ids)]
    if not all(notes):
        raise ValueError("every decision has a note (the page and printed text it rests on)")
    repeated = [note for note, n in Counter(notes).items() if n > 1]
    if repeated:
        raise ValueError(f"{len(repeated)} note(s) repeated across items: each item's note says what is printed where")
    statements = {statement["id"]: statement for statement in gold["statements"]}
    for need in gold["needs_mapping"]:  # statements a person wrote come first: their cells are checked against them
        decision = decisions[need["id"]]
        if need["why"] == "statement_not_found" and decision.get("decision") == "add_statement":
            statement = decision.get("statement") or {}
            if (set(statement) != set(STATEMENT_KEYS) or statement["kind"] != need["kind"] or statement["id"] in statements
                    or not isinstance(statement["page"], int) or not isinstance(statement["end_page"], int)
                    or statement["end_page"] < statement["page"] or statement["consolidated"] is not True):
                raise ValueError(f"{need['id']}: 'add_statement' needs a new consolidated {need['kind']} statement "
                                 f"with exactly {', '.join(STATEMENT_KEYS)}")
            statements[statement["id"]] = statement
    printed = {s["kind"] for s in gold["statements"] if s.get("consolidated")}
    unscorable = []
    cells = list(gold["cells"])
    added: list[dict] = []
    for need in gold["needs_mapping"]:
        decision = decisions[need["id"]]
        kind = decision.get("decision")
        if kind not in ALLOWED.get(need["why"], set()):
            raise ValueError(f"{need['id']} ({need['why']}): decision {kind!r} is not one of {sorted(ALLOWED[need['why']])}")
        if kind == "drop":
            key = f"{need['statement_id']}|{need['page']}|{need['label']}|{need['period']}|{need['printed']}"
            index = next((i for i, c in enumerate(cells) if cell_key(c) == key), None)
            if index is None:
                raise ValueError(f"{need['id']}: no gold cell {key} to drop")
            cells.pop(index)
        elif kind in ("add", "add_statement"):
            given = decision["cells"] if "cells" in decision else need.get("proposed")
            if not given:
                raise ValueError(f"{need['id']}: '{kind}' needs at least one cell")
            checked = [_checked_cell(cell, statements, f"mapping:{need['id']}") for cell in given]
            if kind == "add_statement" and any(c["statement_id"] != decision["statement"]["id"] for c in checked):
                raise ValueError(f"{need['id']}: the cells of 'add_statement' belong to the statement it adds")
            added += checked
        elif kind == "same_statement":
            other = {"IS": "CIS", "CIS": "IS"}.get(need["kind"])
            if other not in printed:
                raise ValueError(f"{need['id']}: 'same_statement' is for 손익/포괄손익 when the other one is printed")
        elif kind == "unscorable":
            unscorable.append(f"{need['id']}: {decision['note']}")
    places = Counter(_place(c) for c in cells + added)
    for cell in added:
        if places[_place(cell)] > 1:
            raise ValueError(f"{cell['source']}: a gold cell is already at {'|'.join(map(str, _place(cell)))}")
    new_statements = [s for s in statements.values() if s not in gold["statements"]]
    return {**gold, "statements": gold["statements"] + new_statements, "cells": cells + added,
            "unscorable": unscorable, "mapping": {k: mapping.get(k) for k in ("status", "confirmed_by", "confirmed_at")}}


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
    printed = [c for c in gold["cells"] if c["value"] is not None]
    print(f"{len(gold['statements'])} statements, {len(printed)} cells (+{len(gold['cells']) - len(printed)} dashes), "
          f"{len(gold['needs_mapping'])} to map")
    return 0


if __name__ == "__main__":
    sys.exit(main())
