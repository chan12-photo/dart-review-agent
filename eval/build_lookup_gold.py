"""Build the gold answers for the development lookup questions (docs/EVAL_DESIGN.ko.md section 12.4).

Same method as eval/build_gold.py, whose independent helpers it reuses:
- the evidence cells are named by hand in eval/dev_lookup.json and read
  straight from the cached responses (``read_cell``);
- the period each cell covers comes from build_gold's own column table, not
  from dart_review.periods;
- "no later report presents this period" and "no report's current column
  covers this period" are checked against that table too, and "the later
  report is not cached" against the cache.

The product code (dart_review.tools.lookup_value for lookups, the keyword
rules for out-of-scope and company questions) is then run on the same
question; every status, value, receipt number, and named reason must match.

    python eval/build_lookup_gold.py          # write eval/dev_lookup_gold.json
    python eval/build_lookup_gold.py --check  # fail if the committed file is stale
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from build_gold import (  # noqa: E402
    END_MONTH, GoldError, _names_cells, cell_period, period_label, period_range, read_cell, require_period, spec_period,
)
from dart_review.accounts import ACCOUNTS  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient, NotCached  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS, ensure_not_sealed  # noqa: E402

SPEC = ROOT / "eval" / "dev_lookup.json"
GOLD = ROOT / "eval" / "dev_lookup_gold.json"
CACHE = ROOT / "cache"
LOOKUP_STATUSES = ("값 확인", "확인 필요", "데이터 없음", "조회 불가")
ALL_COLUMNS = ("thstrm", "thstrm_add", "frmtrm", "frmtrm_q", "frmtrm_add", "bfefrmtrm")


def covering_columns(year: int, report_code: str, sj_div: str, period: tuple[int, int, int]) -> list[str]:
    found = []
    for column in ALL_COLUMNS:
        try:
            if cell_period({"year": year, "report_code": report_code, "column": column, "sj_div": sj_div}) == period:
                found.append(column)
        except GoldError:
            continue  # this statement has no such column in this report
    return found


def build_lookup(client: DartClient, question: dict[str, Any]) -> dict[str, Any]:
    expected, question_id = question["expected"], question["id"]
    corp_code, fs_div, status = expected["corp_code"], expected["fs_div"], expected["status"]
    ensure_not_sealed(corp_code)
    if corp_code not in DEV_COMPANIES or status not in LOOKUP_STATUSES:
        raise GoldError(f"{question_id}: not a development company or an unknown status")
    period = spec_period(expected["period"])
    gold: dict[str, Any] = {
        "id": question_id, "question": question["question"], "case_types": question["case_types"], "action": "lookup",
        "company": DEV_COMPANIES[corp_code], "corp_code": corp_code, "status": status, "expected_status": status,
        "decision": "answer" if status in ("값 확인", "확인 필요") else "refuse",
        "account": expected["account"], "account_label": ACCOUNTS[expected["account"]].label,
        "basis": FS_DIVS[fs_div], "fs_div": fs_div, "period": period_label(period), "period_range": period_range(period),
        "reason_keywords": expected.get("reason_keywords", []), "forbidden_terms": [], "values": {}}
    evidence = expected.get("evidence", {})
    if status == "조회 불가":
        report_code = {month: code for code, month in END_MONTH.items()}.get(period[1])
        current = [column for column in covering_columns(period[0], report_code, expected["sj_div"], period)
                   if column in ("thstrm", "thstrm_add")] if report_code else []
        if current:
            raise GoldError(f"{question_id}: report {report_code} presents the period in {current}; it is not 조회 불가")
        return gold
    value = evidence["value"]
    if "expect_status" not in value:
        require_period(question_id, "value", value, period)
        if value["column"] not in ("thstrm", "thstrm_add"):
            raise GoldError(f"{question_id}: a lookup reads the report whose current period it is")
    gold["values"] = {"current": read_cell(client, corp_code, fs_div, value)}
    if status == "데이터 없음":
        return gold
    if "later" in evidence:
        later_spec = evidence["later"]
        require_period(question_id, "later", later_spec, period)
        if (later_spec["year"], later_spec["report_code"]) != (value["year"] + 1, value["report_code"]):
            raise GoldError(f"{question_id}: the later report is the same kind of report a year later")
        later = read_cell(client, corp_code, fs_div, later_spec)
        current = gold["values"]["current"]
        restated = later["amount"] != current["amount"]
        if restated != (status == "확인 필요"):
            raise GoldError(f"{question_id}: the later figure {'differs' if restated else 'agrees'}, status {status}")
        gold["later"] = later
    else:
        missing = evidence["later_missing"]
        if (missing["year"], missing["report_code"]) != (value["year"] + 1, value["report_code"]):
            raise GoldError(f"{question_id}: later_missing names the wrong report")
        columns = [column for column in covering_columns(missing["year"], missing["report_code"], value["sj_div"], period)
                   if column not in ("thstrm", "thstrm_add")]
        if missing["why"] == "no_column":
            if columns:
                raise GoldError(f"{question_id}: the later report does present the period ({columns})")
        else:
            try:
                client.financial_statements(corp_code, missing["year"], missing["report_code"], fs_div)
                raise GoldError(f"{question_id}: the later report is cached")
            except NotCached:
                pass
        gold["later_missing"] = missing["why"]
    return gold


def build_other(question: dict[str, Any]) -> dict[str, Any]:
    expected = question["expected"]
    gold = {"id": question["id"], "question": question["question"], "case_types": question["case_types"],
            "action": expected["action"], "company": expected["company"], "account": None, "forbidden_terms": []}
    if expected["action"] == "clarify_company":
        gold.update(expected_status="되묻기", decision="clarify",
                    options=[{"account": None, "label": name} for name in expected["options"]])
    elif expected["action"] == "out_of_scope":
        gold.update(expected_status="범위 밖", decision="refuse", scope=expected["scope"])
    else:
        raise GoldError(f"{question['id']}: unknown action {expected['action']}")
    return gold


def cross_check(client: DartClient, question: dict[str, Any], gold: dict[str, Any], reference_date: date) -> list[str]:
    """Differences between the hand-specified gold and the product code (empty when they agree)."""
    from dart_review.baseline import read
    from dart_review.tools import lookup_value

    expected = question["expected"]
    if expected["action"] != "lookup":
        reading = read(question["question"], reference_date)
        if expected["action"] == "clarify_company":
            ok = (reading.kind, reading.company, list(reading.options)) == ("clarify_company", gold["company"],
                                                                             [option["label"] for option in gold["options"]])
        else:
            ok = reading.kind == "unsupported" and reading.arguments["scope"] == gold["scope"]
            ok = ok and (reading.company == gold["company"])
        return [] if ok else [f"the rules read {reading}"]
    result = lookup_value(client, gold["company"], gold["basis"], gold["account"], expected["period"])
    problems = []
    if result["status"] != gold["status"]:
        problems.append(f"status: product {result['status']}, gold {gold['status']}")
    for role, key in (("current", "value"), ("later", "later")):
        cell = gold["values"].get("current") if role == "current" else gold.get("later")
        if cell and "amount" in cell:
            ours = result.get(key) or {}
            if (ours.get("amount"), ours.get("rcept_no"), ours.get("report")) != (cell["amount"], cell["rcept_no"],
                                                                                  f"{cell['year']}년 {cell['report']}"):
                problems.append(f"{key}: product {ours}, gold {cell['amount']} {cell['rcept_no']}")
    for keyword in gold["reason_keywords"]:
        if not any(keyword in reason for reason in result["reasons"]):
            problems.append(f"no reason mentions {keyword!r}: {result['reasons']}")
    if gold["status"] == "확인 필요" and "later" in gold and not any(
            _names_cells(reason, [gold["values"]["current"], gold["later"]]) for reason in result["reasons"]):
        problems.append("no reason names both figures and receipt numbers")
    if "later_missing" in gold and not any("재작성 여부는 확인하지 않았다" in note for note in result["notes"]):
        problems.append("the product does not say the later report was not checked")
    if gold["status"] == "값 확인" and "later" in gold and not any("일치" in note for note in result["notes"]):
        problems.append("the product does not say the later report agrees")
    return problems


def build(client: DartClient, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    ids = [question["id"] for question in spec["questions"]]
    if len(ids) != len(set(ids)):
        raise GoldError("question ids are not unique")
    reference_date = date.fromisoformat(spec["reference_date"])
    answers, problems = [], []
    for question in spec["questions"]:
        gold = build_lookup(client, question) if question["expected"]["action"] == "lookup" else build_other(question)
        problems += [f"{question['id']}: {problem}" for problem in cross_check(client, question, gold, reference_date)]
        answers.append(gold)
    document = {"version": spec["version"], "source": "eval/dev_lookup.json", "rules": spec["rules"],
                "status": spec["status"], "reference_date": spec["reference_date"], "answers": answers}
    return document, problems


def no_key() -> str:
    raise GoldError("building the gold answers must not need the API key; fetch the cache first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
    document, problems = build(client, json.loads(SPEC.read_text(encoding="utf-8")))
    if problems:
        print("the gold answers and the product code disagree:\n  " + "\n  ".join(problems))
        return 1
    text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        current = GOLD.read_text(encoding="utf-8") if GOLD.exists() else ""
        print(f"{len(document['answers'])} answers agree with the product code; "
              + ("dev_lookup_gold.json is up to date" if current == text else "dev_lookup_gold.json is STALE"))
        return 0 if current == text else 1
    GOLD.write_text(text, encoding="utf-8")
    print(f"{len(document['answers'])} answers agree with the product code -> {GOLD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
