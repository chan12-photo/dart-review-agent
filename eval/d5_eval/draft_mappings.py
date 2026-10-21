"""Claude's first-pass D5 mapping decisions (D4 contract 4.2, D5 contract 6), each with the evidence it rests on.

    python eval/d5_eval/draft_mappings.py --pdf-dir ~/Desktop/D5                   # writes the drafts
    python eval/d5_eval/draft_mappings.py --pdf-dir ~/Desktop/D5 --replace-drafts  # rewrites them, refusing any
                                                                                    # that is no longer a draft

Most items follow from the PDF's text layer (the gold builder's own ``lines_of``) and the gold, by three rules, and
every note quotes what it rests on:
- ``not_in_dart`` (a printed cell OpenDART does not have): "keep" when exactly one line of its page prints its label
  and its amount, and the amount is that line's amount of its period (of the line's last two amounts, the first is
  당기 and the second 전기). The print is the answer; OpenDART (XBRL) groups those accounts otherwise. A cell that
  fails the column test (한독's column header read as a row) is decided in ``EXPLICIT``.
- ``dart_only`` (an OpenDART value printed nowhere as a gold cell): "ignore" when the amount is printed nowhere on
  the statement's pages. When printed gold cells of the same statement and period sum to it (up to three, with
  signs), the note gives that sum.
- ``dart_only`` whose amount is printed on a line that is already a gold cell of the same statement, period, and
  value (OpenDART reports one printed number under two names, e.g. 기본 and 희석 on one printed row, or a parent's
  share equal to the total): "ignore", naming that cell.
Any other item stops the script unless ``EXPLICIT`` decides it; those decisions were read off the page by Claude.
The user reads and confirms them (status "confirmed"); until then no score is official.
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from d4_gold import apply_mapping, label_key, lines_of  # noqa: E402

GOLD = ROOT / "eval" / "d5_eval" / "gold"
PERIOD = {0: "당기", 1: "전기"}
BASIS = ("PDF 글자 층(정답 생성기의 lines_of)의 인쇄 줄과 정답, OpenDART 캐시(cache/d4, fnlttSinglAcntAll, 2025, 11011, "
         "CFS)를 항목마다 대조했다. 합·차는 원 단위 정수로 계산해 맞는 것만 적었다. 사용자 확인 전이다.")


def cell(statement_id: str, page: int, label: str, period: int, printed: str, value: int | None) -> dict:
    return {"statement_id": statement_id, "page": page, "label": label, "period": period, "printed": printed, "value": value}


CHA_CF = "연결현금흐름표@13"
EXPLICIT: dict[str, dict[str, dict]] = {
    "27_00525679": {  # 차바이오텍
        "n1": {"decision": "add", "note": (
            "14쪽 '투자활동으로 인한 현금흐름 (140,399,768,396) - 7,364,500,574': 이 현금흐름표는 당기 세부·당기 합계·전기 세부·"
            "전기 합계 네 열이다(금액 오른쪽 끝 319·394·469·543, 같은 쪽 '영업활동으로 인한 현금흐름'도 394·543). "
            "(140,399,768,396)은 당기 합계 열(394), 7,364,500,574는 전기 합계 열(543)이고, '-'는 전기 세부 열(469)이다. "
            "두 합계가 OpenDART '투자활동으로 인한 현금흐름' 당기 -140,399,768,396, 전기 7,364,500,574와 같다. 합계 두 칸을 더한다."),
            "cells": [cell(CHA_CF, 14, "투자활동으로 인한 현금흐름", 0, "(140,399,768,396)", -140399768396),
                      cell(CHA_CF, 14, "투자활동으로 인한 현금흐름", 1, "7,364,500,574", 7364500574)]},
        "n13": {"decision": "ignore", "note": (
            "OpenDART '투자활동으로 인한 현금흐름' 당기 -140,399,768,396은 14쪽 같은 줄의 당기 합계 칸으로, n1의 결정으로 정답에 "
            "들어간다. 따로 더하지 않는다.")},
        "n14": {"decision": "ignore", "note": (
            "OpenDART '투자활동으로 인한 현금흐름' 전기 7,364,500,574는 14쪽 같은 줄의 전기 합계 칸으로, n1의 결정으로 정답에 "
            "들어간다. 따로 더하지 않는다.")},
    },
    "30_00161046": {  # 한독
        "n1": {"decision": "drop", "note": (
            "8쪽 '과 목 주석 제 68 기 기말 제 67 기 기말'은 재무상태표의 열 머리글이다. 정답 생성기가 이 줄을 행으로 읽어 "
            "계정명 '과 목 주석 제', 전기 67(기수 '제 67 기')을 칸으로 만들었다. 금액이 아니므로 뺀다.")},
    },
    "33_01586455": {  # 꿈비
        "n12": {"decision": "same_statement", "note": (
            "OpenDART에는 연결포괄손익계산서가 있지만 인쇄본에는 그 제목의 표가 없다. 9쪽 '연 결 손 익 계 산 서'(제목 위치 54) "
            "한 표에 'VII.당기순이익(손실)' 다음으로 'VIII. 기타포괄손익 350,283,129 (38,632,647)', 'Ⅸ. 당기총포괄이익(손실) "
            "(14,721,294,519) (2,697,268,922)', 주당이익까지 이어서 인쇄돼 있다(10쪽은 연결자본변동표). 손익과 포괄손익을 한 "
            "표가 함께 보여 주므로 같은 재무제표로 본다.")},
    },
}


def _amount_forms(value: int) -> list[str]:
    return [f"{abs(value):,}"]


def _printed_on(line: dict, form: str) -> bool:
    """``form`` is one of the line's printed amounts: a word of its own, without parentheses or a sign. The words,
    not the line without spaces: two amounts side by side ("1,210 707") joined into "1,210707" hid both of them
    (Codex D5 pre-registration review 1)."""
    return any(re.sub(r"^[(\-−]+|[)]+$", "", word["text"]) == form for word in line["words"])


def _sum_note(cells: list[dict], value: int) -> str:
    for n in (2, 3):
        for group in itertools.combinations(cells, n):
            for signs in itertools.product((1, -1), repeat=n):
                if sum(sign * c["value"] for sign, c in zip(signs, group)) == value:
                    parts = " ".join(("+ " if sign > 0 else "- ") + f"'{c['label']}' {c['printed']}"
                                     for sign, c in zip(signs, group)).lstrip("+ ")
                    return f" 인쇄된 정답 칸으로 {parts} = {value:,}이다."
    return " 인쇄된 정답 칸 셋 이하의 합으로는 나오지 않는다."


def decide(key: str, gold: dict, lines: list[dict]) -> dict[str, dict]:
    statements = {s["id"]: s for s in gold["statements"]}
    decisions = {}
    for need in gold["needs_mapping"]:
        explicit = EXPLICIT.get(key, {}).get(need["id"])
        if explicit:
            decisions[need["id"]] = explicit
            continue
        if need["why"] == "not_in_dart":
            printed = re.sub(r"\s+", "", need["printed"])
            hits = [l for l in lines if l["page"] == need["page"] and printed in l["compact"]
                    and label_key(need["label"]) in label_key(l["text"])]
            if len(hits) != 1:
                raise ValueError(f"{key} {need['id']}: {len(hits)} printed lines for {need['label']} {need['printed']}")
            amounts = [w["text"] for w in hits[0]["words"] if re.fullmatch(r"\(?-?[\d,]+\)?|-", w["text"])
                       and ("," in w["text"] or w["text"] == "-")]
            if len(amounts) < 2 or amounts[-2 + need["period"]] != need["printed"]:
                raise ValueError(f"{key} {need['id']}: {need['printed']} is not the {PERIOD[need['period']]} amount of "
                                 f"'{hits[0]['text']}': decide it in EXPLICIT")
            decisions[need["id"]] = {"decision": "keep", "note": (
                f"{need['page']}쪽 '{hits[0]['text']}': '{need['label']}' {PERIOD[need['period']]} {need['printed']}이 이 줄에 "
                f"인쇄돼 있다. OpenDART에는 이 재무제표·기간에 이 값의 항목이 없다(XBRL이 계정을 다르게 묶었다). 인쇄가 정답이므로 둔다.")}
        elif need["why"] == "dart_only":
            statement = statements[need["statement_id"]]
            pages = range(statement["page"], statement.get("end_page", statement["page"]) + 1)
            value = need["value"]
            forms = _amount_forms(value)
            hits = [l for l in lines if l["page"] in pages and any(_printed_on(l, f) for f in forms)]
            same = [c for c in gold["cells"] if c["statement_id"] == need["statement_id"] and c["period"] == need["period"]
                    and c["value"] == value]
            span = f"{pages[0]}~{pages[-1]}쪽" if len(pages) > 1 else f"{pages[0]}쪽"
            name = f"OpenDART '{need['name']}' {PERIOD[need['period']]} {value:,}"
            if not hits:
                cells = [c for c in gold["cells"] if c["statement_id"] == need["statement_id"]
                         and c["period"] == need["period"] and c["value"] is not None]
                decisions[need["id"]] = {"decision": "ignore", "note": (
                    f"{name}: {statement['title']} {span} 어디에도 '{forms[0]}'가 인쇄돼 있지 않다." + _sum_note(cells, value))}
                continue
            on_line = [c for c in same if any(l["page"] == c["page"] and label_key(c["label"]) in label_key(l["text"])
                                              for l in hits)]
            if not on_line:
                raise ValueError(f"{key} {need['id']}: printed but not a gold cell: decide it in EXPLICIT")
            c = on_line[0]
            line = next(l for l in hits if l["page"] == c["page"] and label_key(c["label"]) in label_key(l["text"]))
            decisions[need["id"]] = {"decision": "ignore", "note": (
                f"{name}: {c['page']}쪽 '{line['text']}'에 한 번 인쇄된 값이고, 이 줄은 이미 정답 칸('{c['label']}' "
                f"{PERIOD[c['period']]} {c['printed']})이다. OpenDART가 인쇄된 한 숫자를 두 이름으로 담은 것이라 더하지 않는다.")}
        else:
            raise ValueError(f"{key} {need['id']} ({need['why']}): decide it in EXPLICIT")
    return decisions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--replace-drafts", action="store_true")
    args = parser.parse_args(argv)
    pdfs = {p.name.split("_")[0]: p for p in args.pdf_dir.expanduser().glob("*.pdf")}
    for gold_path in sorted(GOLD.glob("*.gold.json")):
        key = gold_path.name.split(".")[0]
        out = GOLD / f"{key}.mapping.json"
        if out.exists():
            if not args.replace_drafts:
                raise SystemExit(f"{out.name} exists (--replace-drafts rewrites a draft)")
            if json.loads(out.read_text(encoding="utf-8")).get("status") != "draft":
                raise SystemExit(f"{out.name} is no longer a draft: not replaced")
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        mapping = {"status": "draft", "basis": BASIS, "decisions": decide(key, gold, lines_of(pdfs[key.split("_")[0]]))}
        applied = apply_mapping(gold, mapping)  # every rule of the scorer, before anything is written
        out.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        kinds = {}
        for d in mapping["decisions"].values():
            kinds[d["decision"]] = kinds.get(d["decision"], 0) + 1
        printed = sum(1 for c in applied["cells"] if c["value"] is not None)
        print(f"{key}: {kinds}; gold cells {printed} (+{len(applied['cells']) - printed} dashes); "
              f"unscorable {applied['unscorable'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
