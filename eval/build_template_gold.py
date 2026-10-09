"""Gold answers for the 3-5 template evaluation (docs/EVAL_CONTRACT_3-5.ko.md section 5).

Two parts:

1. The gold-side rules the question generator uses to fill in each question's
   expectation from the raw cache, without the product code:
   - which row is the account (``select_cell``, section 5.3): the standard-id
     total row, statements in order (IS before CIS; when both carry net income
     the two amounts must agree), else a non-standard row whose name is in the
     gold name table, else the combination is excluded;
   - the status (section 5.2): one report -> 비교 가능; a balance-sheet
     quarter-end compared with the prior year -> 비교 가능 only if the two
     values linking the three reports agree (``link_pairs``); a lookup ->
     확인 필요 when the same kind of report a year later shows another figure;
   - the wording when the sign changes (GOLD_RULES section 3).
2. Building gold.json from the generated questions with the independent
   builders of eval/build_gold.py and eval/build_lookup_gold.py (as the 3-1
   builder does), then running the product's rules on every question and
   writing every disagreement to gold_disagreements.json for a decision
   (section 5.4). A disagreement does not stop the build.

    python eval/build_template_gold.py          # write gold.json and gold_disagreements.json
    python eval/build_template_gold.py --check  # fail if either committed file is stale

Shared with the product: the cache and client, company names, account labels
and the product's account-name list (extended by the gold name table).
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import build_gold  # noqa: E402
import build_lookup_gold  # noqa: E402
from build_gold import GoldError, cell_period, read_cell, spec_period  # noqa: E402
from dart_review.accounts import ACCOUNTS  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient, NotCached  # noqa: E402
from dart_review.companies import SEALED_EVAL_COMPANIES, using_company_set  # noqa: E402

FOLDER = ROOT / "eval" / "template_3-5"
QUESTIONS, GOLD, DISAGREEMENTS = FOLDER / "questions.json", FOLDER / "gold.json", FOLDER / "gold_disagreements.json"
CACHE = ROOT / "cache"
REPORT_OF_MONTH = {3: "11013", 6: "11012", 9: "11014", 12: "11011"}
NON_STANDARD = "-표준계정코드 미사용-"
# Section 5.3 (user decision 2026-10-09): a name seen in the sealed data after 3-1, not in the product's list.
GOLD_EXTRA_NAMES = {"operating_cash_flow": ("영업활동으로부터의 순현금유입",)}
NOT_COMPARABLE = "비교 불가"
_INTEGER = re.compile(r"-?\d+")


class Excluded(Exception):
    """The gold cannot name exactly one usable cell: the combination is left out (contract section 4.1, step 2)."""


# ---------------------------------------------------------------- which row (section 5.3)

def _total_rows(rows: list[dict[str, Any]], sj_div: str) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("sj_div") == sj_div and (row.get("account_detail") or "-") == "-"]


def _amount(row: dict[str, Any], column: str) -> int | None:
    text = (row.get(f"{column}_amount") or "").replace(",", "")
    return int(text) if _INTEGER.fullmatch(text) else None


def _response_rows(client: DartClient, corp_code: str, fs_div: str, year: int, report_code: str) -> list[dict[str, Any]]:
    try:
        response = client.financial_statements(corp_code, year, report_code, fs_div)
    except NotCached as exc:
        raise Excluded(f"{year} {report_code} {fs_div}: not in the cache") from exc
    if response.status != "000":
        raise Excluded(f"{year} {report_code} {fs_div}: status {response.status}")
    return response.json()["list"]


def select_cell(client: DartClient, corp_code: str, fs_div: str, account: str, year: int, report_code: str,
                column: str) -> dict[str, Any]:
    """The evidence cell for one account in one column of one report, chosen by the gold rule."""
    rows = _response_rows(client, corp_code, fs_div, year, report_code)
    definition = ACCOUNTS[account]
    where = f"{corp_code} {fs_div} {year} {report_code} {column} {account}"
    standard = {sj_div: [row for row in _total_rows(rows, sj_div) if row.get("account_id") == definition.account_id]
                for sj_div in definition.statements}
    chosen = None
    for sj_div in definition.statements:
        hits = standard[sj_div]
        if len(hits) > 1:
            raise Excluded(f"{where}: {len(hits)} standard-id total rows in {sj_div}")
        if hits:
            chosen = {"sj_div": sj_div, "account_id": definition.account_id}
            break
    if chosen and len(definition.statements) > 1:
        # the same standard id in IS and CIS (net income): checked equal before it is relied on (section 5.3)
        amounts = {sj_div: _amount(hits[0], column) for sj_div, hits in standard.items() if len(hits) == 1}
        if len(set(amounts.values())) > 1:
            raise GoldError(f"{where}: the IS and CIS rows differ: {amounts}")
    if chosen is None:
        names = set(definition.names) | set(GOLD_EXTRA_NAMES.get(account, ()))
        for sj_div in definition.statements:
            hits = [row for row in _total_rows(rows, sj_div)
                    if row.get("account_id") in (NON_STANDARD, "", None) and row.get("account_nm") in names]
            if len(hits) > 1:
                raise Excluded(f"{where}: {len(hits)} non-standard rows with an account name")
            if hits:
                chosen = {"sj_div": sj_div, "account_id": hits[0].get("account_id"), "account_nm": hits[0]["account_nm"]}
                break
    if chosen is None:
        raise Excluded(f"{where}: no row")
    row = [item for item in _total_rows(rows, chosen["sj_div"]) if item.get("account_id") == chosen["account_id"]
           and ("account_nm" not in chosen or item.get("account_nm") == chosen["account_nm"])][0]
    if _amount(row, column) is None or not row.get("currency"):
        raise Excluded(f"{where}: the cell is empty or has no currency")
    return {"year": year, "report_code": report_code, "column": column, **chosen}


def is_non_standard(cell: dict[str, Any]) -> bool:
    return "account_nm" in cell


# ---------------------------------------------------------------- columns (DATA_NOTES section 1, written apart from periods.py)

def statement_kind(account: str) -> str:
    return {"BS": "BS", "CF": "CF"}.get(ACCOUNTS[account].statements[0], "IS")


def own_column(account: str, period: dict[str, Any]) -> tuple[int, str, str]:
    """(year, report, column) of the report whose current column is ``period``."""
    kind, year, month = period["kind"], period["year"], period["month"]
    report_code = REPORT_OF_MONTH[month]
    if statement_kind(account) == "IS" and kind == "year_to_date" and month in (6, 9):
        return year, report_code, "thstrm_add"
    return year, report_code, "thstrm"


def prior_year_column(account: str, period: dict[str, Any]) -> str | None:
    """The column of the same report that presents the same period one year earlier (None: not presented)."""
    kind, month = period["kind"], period["month"]
    statement = statement_kind(account)
    if month == 12:
        return "frmtrm"
    if statement == "BS":
        return None  # a quarterly balance sheet presents the prior year end, not the prior quarter end
    if statement == "CF":
        return "frmtrm_q"
    return "frmtrm_add" if kind == "year_to_date" and month in (6, 9) else "frmtrm_q"


def check_cell_period(question_id: str, role: str, cell: dict[str, Any], period: dict[str, Any]) -> None:
    if cell_period(cell) != spec_period(period):
        raise GoldError(f"{question_id} {role}: the column table puts {cell} at {cell_period(cell)}, not {period}")


def cached(client: DartClient, corp_code: str, fs_div: str, year: int, report_code: str) -> bool:
    try:
        client.financial_statements(corp_code, year, report_code, fs_div)
        return True
    except NotCached:
        return False


# ---------------------------------------------------------------- status and wording (section 5.2, GOLD_RULES 3)

def direction(account: str, current: int, base: int) -> str:
    if base > 0 and current >= 0:
        return "증가" if current > base else "감소" if current < base else "변동 없음"
    if ACCOUNTS[account].profit_like:
        if base < 0 < current:
            return "흑자 전환"
        if base > 0 > current:
            return "적자 전환"
        if base < 0 and current < 0:
            return "적자 축소" if current > base else "적자 확대" if current < base else "적자 지속"
    return "증가" if current > base else "감소" if current < base else "변동 없음"


def amount_of(client: DartClient, corp_code: str, fs_div: str, cell: dict[str, Any]) -> tuple[int, str]:
    found = read_cell(client, corp_code, fs_div, cell)
    return found["amount"], found["currency"]


def link_pairs(client: DartClient, corp_code: str, fs_div: str, account: str, year: int, month: int) -> list[dict[str, Any]]:
    """The two value pairs linking a Q-end balance sheet with the one a year earlier (section 5.2)."""
    report_code = REPORT_OF_MONTH[month]
    pairs = [
        # the year end two years before: the base report's prior year end and the bridging annual report's prior year
        ({"kind": "instant", "year": year - 2, "month": 12}, (year - 1, report_code, "frmtrm"), (year - 1, "11011", "frmtrm")),
        # the prior year end: the bridging annual report's current year and the current report's prior year end
        ({"kind": "instant", "year": year - 1, "month": 12}, (year - 1, "11011", "thstrm"), (year, report_code, "frmtrm")),
    ]
    found = []
    for period, *places in pairs:
        cells = [select_cell(client, corp_code, fs_div, account, *place) for place in places]
        values = [amount_of(client, corp_code, fs_div, cell) for cell in cells]
        found.append({"period": period, "cells": cells, "agree": values[0] == values[1]})
    return found


# ---------------------------------------------------------------- one grid item -> its expectation

def expectation(client: DartClient, item: dict[str, Any]) -> dict[str, Any]:
    """The expected answer of one generated question (the "expected" entry of questions.json), or Excluded."""
    kind = item["kind"]
    if kind in ("out_of_scope", "clarify_company"):
        return {key: item[key] for key in ("action", "company", "scope", "options") if key in item}
    corp_code, account = item.get("corp_code"), item.get("account")
    if kind == "clarify_account":
        return {"action": "clarify", "corp_code": corp_code, "ambiguity": "account",
                "options": ["operating_income", "net_income"], "fs_div": item["fs_div"],
                **{role: item[role] for role in ("period", "current", "base") if role in item}}
    fs_div = item.get("fs_div")
    if kind == "side_by_side":
        period = item["period"]
        year, report_code, column = own_column(account, period)
        evidence = {fs: select_cell(client, corp_code, fs, account, year, report_code, column) for fs in ("CFS", "OFS")}
        return {"action": "side_by_side", "corp_code": corp_code, "account": account, "period": period,
                "status": NOT_COMPARABLE, "reason_keywords": ["연결과 별도"], "evidence": evidence,
                "forbidden_terms": ["증가", "성장", "늘었", "늘어", "줄었", "감소"]}
    if kind == "lookup":
        return _lookup(client, item)
    if kind in ("lookup_not_provided", "compare_not_provided"):
        keyword = "4분기" if item["period" if kind == "lookup_not_provided" else "current"]["month"] == 12 else "누적 값만"
        if kind == "lookup_not_provided":
            return {"action": "lookup", "corp_code": corp_code, "fs_div": fs_div, "account": account, "period": item["period"],
                    "sj_div": ACCOUNTS[account].statements[0], "status": "조회 불가", "reason_keywords": [keyword]}
        return {"action": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                "current": item["current"], "base": item["base"], "status": NOT_COMPARABLE, "reason_keywords": [keyword],
                "evidence": {}}
    if kind == "lookup_no_data":
        return {"action": "lookup", "corp_code": corp_code, "fs_div": fs_div, "account": account, "period": item["period"],
                "status": "데이터 없음",
                "evidence": {"value": {"year": item["period"]["year"], "report_code": "11011", "expect_status": "013"}}}
    if kind == "compare_no_data":
        return {"action": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                "current": item["current"], "base": item["base"], "status": "데이터 없음",
                "evidence": {"current": {"year": item["current"]["year"], "report_code": "11011", "expect_status": "013"}}}
    if kind == "compare":
        return _compare(client, item)
    raise GoldError(f"unknown kind {kind}")


def _lookup(client: DartClient, item: dict[str, Any]) -> dict[str, Any]:
    corp_code, fs_div, account, period = item["corp_code"], item["fs_div"], item["account"], item["period"]
    year, report_code, column = own_column(account, period)
    value = select_cell(client, corp_code, fs_div, account, year, report_code, column)
    later_column = prior_year_column(account, period)
    evidence: dict[str, Any] = {"value": value}
    status = "값 확인"
    if later_column is None:
        evidence["later_missing"] = {"year": year + 1, "report_code": report_code, "why": "no_column"}
    elif not cached(client, corp_code, fs_div, year + 1, report_code):
        evidence["later_missing"] = {"year": year + 1, "report_code": report_code, "why": "not_cached"}
    else:
        later = select_cell(client, corp_code, fs_div, account, year + 1, report_code, later_column)
        evidence["later"] = later
        if amount_of(client, corp_code, fs_div, later) != amount_of(client, corp_code, fs_div, value):
            status = "확인 필요"
    return {"action": "lookup", "corp_code": corp_code, "fs_div": fs_div, "account": account, "period": period,
            "status": status, "evidence": evidence}


def _compare(client: DartClient, item: dict[str, Any]) -> dict[str, Any]:
    corp_code, fs_div, account = item["corp_code"], item["fs_div"], item["account"]
    current, base = item["current"], item["base"]
    year, report_code, column = own_column(account, current)
    current_cell = select_cell(client, corp_code, fs_div, account, year, report_code, column)
    expected: dict[str, Any] = {"action": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                                "current": current, "base": base}
    prior = prior_year_column(account, current)
    if prior is not None:  # one report presents both periods (A3, A4, A5, A7)
        base_cell = select_cell(client, corp_code, fs_div, account, year, report_code, prior)
        expected.update(status="비교 가능", evidence={"current": current_cell, "base": base_cell})
    else:  # a balance-sheet quarter end against the one a year earlier (A6)
        base_year, base_report, base_column = own_column(account, base)
        base_cell = select_cell(client, corp_code, fs_div, account, base_year, base_report, base_column)
        pairs = link_pairs(client, corp_code, fs_div, account, current["year"], current["month"])
        restated = [{"period": pair["period"], "cells": pair["cells"]} for pair in pairs if not pair["agree"]]
        evidence = {"current": current_cell, "base": base_cell, "link_cells": [pair["cells"] for pair in pairs]}
        if restated:
            evidence["restated_pair"] = restated[0]
            if len(restated) > 1:
                evidence["more_restated_pairs"] = restated[1:]
        expected.update(status="확인 필요" if restated else "비교 가능", evidence=evidence)
    values = [amount_of(client, corp_code, fs_div, cell)[0] for cell in (current_cell, base_cell)]
    if not (values[1] > 0 and values[0] >= 0):  # build_gold needs the wording when no rate is shown
        expected["direction"] = direction(account, *values)
    return expected


def tags(expected: dict[str, Any]) -> list[str]:
    """Group labels reported apart (contract sections 4.2 and 5.3)."""
    found = []
    evidence = expected.get("evidence") or {}
    cells = [cell for cell in evidence.values() if isinstance(cell, dict) and "column" in cell]
    if any(is_non_standard(cell) for cell in cells):
        found.append("비표준 행")
    if expected.get("status") == "확인 필요":
        found.append("재작성")
    if expected.get("direction") not in (None, "증가", "감소", "변동 없음"):
        found.append("부호 전환")
    return found


# ---------------------------------------------------------------- gold.json (as the 3-1 builder, section 5.4)

def build(client: DartClient, spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reference_date = date.fromisoformat(spec["reference_date"])
    answers, disagreements = [], []
    with using_company_set("sealed-3-1"), \
            mock.patch.object(build_gold, "DEV_COMPANIES", SEALED_EVAL_COMPANIES), \
            mock.patch.object(build_lookup_gold, "DEV_COMPANIES", SEALED_EVAL_COMPANIES):
        for question in spec["questions"]:
            again = expectation(client, question["grid"])
            if again != question["expected"]:
                raise GoldError(f"{question['id']}: the expectation in questions.json is not what the gold rules give now")
            action = question["expected"]["action"]
            if action == "lookup":
                gold = build_lookup_gold.build_lookup(client, question)
            elif action in ("clarify_company", "out_of_scope"):
                gold = build_lookup_gold.build_other(question)
            else:
                gold = build_gold.build_question(client, question)
            _check_extra(client, question, gold)
            gold.update(bundle=question["bundle"], author=question["author"], tags=question["tags"])
            try:
                problems = (build_lookup_gold.cross_check(client, question, gold, reference_date)
                            if action in ("lookup", "clarify_company", "out_of_scope")
                            else build_gold.cross_check(client, question, gold))
            except Exception as exc:  # the product's rules failing on a question is a finding, not a build error
                problems = [f"the product's rules raised {type(exc).__name__}: {exc}"]
            if problems:
                disagreements.append({"id": question["id"], "question": question["question"], "tags": question["tags"],
                                      "gold_status": gold.get("status"), "problems": problems})
            answers.append(gold)
    document = {"version": spec["version"], "source": "eval/template_3-5/questions.json",
                "reference_date": spec["reference_date"], "answers": answers}
    return document, disagreements


def _check_extra(client: DartClient, question: dict[str, Any], gold: dict[str, Any]) -> None:
    """What build_gold does not check for the A6 linking evidence: every link cell covers its period."""
    evidence = question["expected"].get("evidence") or {}
    if "link_cells" in evidence:
        year = question["expected"]["current"]["year"]
        for pair, period in zip(evidence["link_cells"], ({"kind": "instant", "year": year - 2, "month": 12},
                                                         {"kind": "instant", "year": year - 1, "month": 12})):
            for index, cell in enumerate(pair):
                check_cell_period(question["id"], f"link {period['year']}[{index}]", cell, period)
    for extra in evidence.get("more_restated_pairs", []):
        cells = [read_cell(client, gold["corp_code"], gold["fs_div"], cell) for cell in extra["cells"]]
        if cells[0]["amount"] == cells[1]["amount"]:
            raise GoldError(f"{question['id']}: a listed restated pair agrees")
        gold.setdefault("more_restated_pairs", []).append({"period": build_gold.period_label(spec_period(extra["period"])),
                                                           "cells": cells})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    client = DartClient(ResponseCache(CACHE), key_loader=build_gold.no_key, offline=True)
    document, disagreements = build(client, json.loads(QUESTIONS.read_text(encoding="utf-8")))
    gold_text = json.dumps(document, ensure_ascii=False, indent=1) + "\n"
    found = [(item["id"], item["problems"]) for item in disagreements]
    if args.check:
        stale = not GOLD.exists() or GOLD.read_text(encoding="utf-8") != gold_text
        recorded = json.loads(DISAGREEMENTS.read_text(encoding="utf-8")) if DISAGREEMENTS.exists() else {"items": []}
        # a disagreement resolved by correcting the gold disappears from the build but stays in the record
        open_items = [(item["id"], item["problems"]) for item in recorded["items"]
                      if not (item.get("decision") or "").startswith("정답 수정")]
        same = found == open_items
        print(f"{len(document['answers'])} answers; gold.json {'STALE' if stale else 'up to date'}; "
              f"disagreements {'match' if same else 'DIFFER from'} the recorded list ({len(found)})")
        return 0 if not stale and same and client.network_requests == 0 else 1
    GOLD.write_text(gold_text, encoding="utf-8")
    if not DISAGREEMENTS.exists():  # decisions are filled in by hand afterwards; never overwritten here
        DISAGREEMENTS.write_text(json.dumps({"about": "EVAL_CONTRACT_3-5 section 5.4: each item is decided by re-reading "
                                             "the raw cells and approved by the user before any run",
                                             "items": [{**item, "decision": None, "reason": None, "approved_by_user": False}
                                                       for item in disagreements]},
                                            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(document['answers'])} answers -> {GOLD.relative_to(ROOT)}; {len(disagreements)} disagreements with the rules")
    return 0 if client.network_requests == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
