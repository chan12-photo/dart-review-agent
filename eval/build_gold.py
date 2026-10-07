"""Build the development gold answers from the raw cache and cross-check the rule code.

Gold values do not come from the rule code. Each question names its evidence
cells by hand (report, column, statement, account id); this script reads
exactly those cells from the cached responses, computes the change itself,
and only then runs the rule code (``review_change``) on the same question.
Any disagreement stops the build. See docs/GOLD_RULES.ko.md.

    python eval/build_gold.py          # write eval/dev_gold.json
    python eval/build_gold.py --check  # fail if the committed file is stale

Runs offline from the cache and never needs the API key.
"""

from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.accounts import ACCOUNTS  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS, REPORT_CODES, ensure_not_sealed  # noqa: E402
from dart_review.compare import compare  # noqa: E402
from dart_review.facts import fact_from_response  # noqa: E402
from dart_review.periods import Period, instant, quarter, year_to_date  # noqa: E402
from dart_review.review import review_change  # noqa: E402

SPEC = ROOT / "eval" / "dev_questions.json"
GOLD = ROOT / "eval" / "dev_gold.json"
CACHE = ROOT / "cache"
ACTIONS = ("compare", "side_by_side", "clarify")
STATUSES = ("비교 가능", "비교 불가", "데이터 없음", "확인 필요")
CASE_TYPES = ("정상 비교", "연결·별도 함정", "3개월·누적 함정", "전년 분기 추가 조회", "표준계정코드 없음",
              "비교 불가", "데이터 없음", "모호한 질문")
_AMOUNT = re.compile(r"-?\d+")


class GoldError(Exception):
    pass


def make_period(spec: dict[str, Any]) -> Period:
    makers = {"instant": instant, "quarter": quarter, "year_to_date": year_to_date}
    return makers[spec["kind"]](spec["year"], spec["month"])


def read_cell(client: DartClient, corp_code: str, fs_div: str, cell: dict[str, Any]) -> dict[str, Any]:
    """Read one hand-specified cell straight from the cached response."""
    response = client.financial_statements(corp_code, cell["year"], cell["report_code"], fs_div)
    found = {"year": cell["year"], "report": REPORT_CODES[cell["report_code"]], "report_code": cell["report_code"],
             "fs_div": fs_div, "status": response.status, "response_sha256": response.sha256}
    if "expect_status" in cell:
        if response.status != cell["expect_status"]:
            raise GoldError(f"{corp_code} {cell}: expected status {cell['expect_status']}, got {response.status}")
        return found
    if response.status != "000":
        raise GoldError(f"{corp_code} {cell}: status {response.status}")
    rows = [row for row in response.json()["list"]
            if row.get("sj_div") == cell["sj_div"] and row.get("account_id") == cell["account_id"]
            and (row.get("account_detail") or "-") == "-"
            and ("account_nm" not in cell or row.get("account_nm") == cell["account_nm"])]
    if len(rows) != 1:
        raise GoldError(f"{corp_code} {fs_div} {cell}: {len(rows)} matching rows (need exactly 1)")
    row = rows[0]
    text = (row.get(f"{cell['column']}_amount") or "").replace(",", "")
    if not _AMOUNT.fullmatch(text):
        raise GoldError(f"{corp_code} {fs_div} {cell}: amount {text!r} is not an integer")
    found.update(column=cell["column"], sj_div=row["sj_div"], account_id=row["account_id"], account_nm=row["account_nm"],
                 rcept_no=row["rcept_no"], currency=row.get("currency"), amount=int(text))
    return found


def change_of(current: int, base: int, direction: str | None) -> dict[str, Any]:
    """Change, rate, and wording per docs/GOLD_RULES.ko.md section 3."""
    change = current - base
    if base > 0 and current >= 0:
        pct = (Decimal(change) * 100 / Decimal(base)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        computed = "증가" if change > 0 else "감소" if change < 0 else "변동 없음"
        if direction not in (None, computed):
            raise GoldError(f"direction {direction!r} contradicts the sign of the change ({computed})")
        return {"change": change, "change_pct": str(pct), "direction": computed}
    if direction is None:
        raise GoldError("the base is not positive or the sign changes: the question must state the direction")
    return {"change": change, "change_pct": None, "direction": direction}


def validate_spec(spec: dict[str, Any]) -> None:
    ids = [question["id"] for question in spec["questions"]]
    if len(ids) != len(set(ids)):
        raise GoldError("question ids are not unique")
    covered = {case for question in spec["questions"] for case in question["case_types"]}
    missing = [case for case in CASE_TYPES if case not in covered]
    if missing:
        raise GoldError(f"case types without a question: {missing}")
    for question in spec["questions"]:
        expected = question["expected"]
        ensure_not_sealed(expected["corp_code"])
        if expected["corp_code"] not in DEV_COMPANIES:
            raise GoldError(f"{question['id']}: not a development company")
        if expected["action"] not in ACTIONS:
            raise GoldError(f"{question['id']}: unknown action {expected['action']}")
        if expected["action"] != "clarify" and expected["status"] not in STATUSES:
            raise GoldError(f"{question['id']}: unknown status {expected['status']}")
        for key in [expected.get("account")] + expected.get("options", []):
            if key is not None and key not in ACCOUNTS:
                raise GoldError(f"{question['id']}: unknown account {key}")


def build_question(client: DartClient, question: dict[str, Any]) -> dict[str, Any]:
    expected = question["expected"]
    corp_code = expected["corp_code"]
    gold: dict[str, Any] = {"id": question["id"], "question": question["question"], "case_types": question["case_types"],
                            "action": expected["action"], "company": DEV_COMPANIES[corp_code], "corp_code": corp_code}
    if expected["action"] == "clarify":
        gold.update(ambiguity=expected["ambiguity"],
                    options=[{"account": key, "label": ACCOUNTS[key].label} for key in expected["options"]])
        return gold
    gold.update(status=expected["status"], account=expected["account"], account_label=ACCOUNTS[expected["account"]].label,
                reason_keywords=expected.get("reason_keywords", []))
    evidence = expected.get("evidence", {})
    if expected["action"] == "side_by_side":
        gold["period"] = make_period(expected["period"]).label()
        gold["values"] = {fs_div: read_cell(client, corp_code, fs_div, cell) for fs_div, cell in evidence.items()}
        return gold
    fs_div = expected["fs_div"]
    gold.update(basis=FS_DIVS[fs_div], fs_div=fs_div, current_period=make_period(expected["current"]).label(),
                base_period=make_period(expected["base"]).label())
    values = {role: read_cell(client, corp_code, fs_div, evidence[role]) for role in ("current", "base") if role in evidence}
    gold["values"] = values
    if expected["status"] in ("비교 가능", "확인 필요"):
        gold.update(change_of(values["current"]["amount"], values["base"]["amount"], expected.get("direction")))
    if "base_as_originally_reported" in evidence:
        original = read_cell(client, corp_code, fs_div, evidence["base_as_originally_reported"])
        if original["amount"] == values["base"]["amount"]:
            raise GoldError(f"{question['id']}: the original value equals the restated one")
        gold["base_as_originally_reported"] = original
    if "restated_pair" in evidence:
        pair = [read_cell(client, corp_code, fs_div, cell) for cell in evidence["restated_pair"]]
        if pair[0]["amount"] == pair[1]["amount"]:
            raise GoldError(f"{question['id']}: the restated pair has equal amounts")
        gold["restated_pair"] = pair
    return gold


def _same_cell(fact: Any, cell: dict[str, Any]) -> bool:
    return (fact is not None and fact.amount == cell["amount"] and fact.rcept_no == cell["rcept_no"]
            and (fact.source.year, fact.source.report_code, fact.source.column) == (cell["year"], cell["report_code"], cell["column"])
            and (fact.sj_div, fact.account_id) == (cell["sj_div"], cell["account_id"]))


def cross_check(client: DartClient, question: dict[str, Any], gold: dict[str, Any]) -> list[str]:
    """Differences between the hand-specified gold and the rule code (empty when they agree)."""
    expected = question["expected"]
    if expected["action"] == "clarify":
        return []
    problems = []
    if expected["action"] == "side_by_side":
        facts = {fs_div: fact_from_response(
            client.financial_statements(expected["corp_code"], cell["year"], cell["report_code"], fs_div), expected["account"], cell["column"])
            for fs_div, cell in gold["values"].items()}
        result = compare(facts["CFS"], facts["OFS"])
        problems += [f"{fs_div} value differs" for fs_div, fact in facts.items() if not _same_cell(fact, gold["values"][fs_div])]
    else:
        result = review_change(client, expected["corp_code"], expected["fs_div"], expected["account"],
                               make_period(expected["current"]), make_period(expected["base"]))
        for role, cell in gold["values"].items():
            if "amount" in cell and not _same_cell(getattr(result, role), cell):
                problems.append(f"{role} value or source differs: rules gave {getattr(result, role)}")
        for key in ("change", "change_pct", "direction"):
            ours = getattr(result, key)
            ours = str(ours) if key == "change_pct" and ours is not None else ours
            if key in gold and ours != gold[key]:
                problems.append(f"{key}: rules {ours!r}, gold {gold[key]!r}")
        if "base_as_originally_reported" in gold:
            original = f"{gold['base_as_originally_reported']['amount']:,}"
            if not any(original in note for note in result.notes):
                problems.append(f"the rules do not note the original value {original}")
    if result.status != gold["status"]:
        problems.append(f"status: rules {result.status}, gold {gold['status']}")
    for keyword in gold["reason_keywords"]:
        if not any(keyword in reason for reason in result.reasons):
            problems.append(f"no reason mentions {keyword!r}: {result.reasons}")
    return problems


def build(client: DartClient, spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    validate_spec(spec)
    answers, problems = [], []
    for question in spec["questions"]:
        gold = build_question(client, question)
        problems += [f"{question['id']}: {problem}" for problem in cross_check(client, question, gold)]
        answers.append(gold)
    document = {"version": spec["version"], "source": "eval/dev_questions.json", "rules": spec["rules"],
                "status": spec["status"], "answers": answers}
    return document, problems


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def no_key() -> str:
    raise GoldError("building the gold answers must not need the API key; fetch the cache first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="verify eval/dev_gold.json instead of writing it")
    args = parser.parse_args(argv)
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
    document, problems = build(client, json.loads(SPEC.read_text(encoding="utf-8")))
    for problem in problems:
        print("MISMATCH", problem)
    if problems:
        return 1
    text = render(document)
    if args.check:
        stale = not GOLD.exists() or GOLD.read_text(encoding="utf-8") != text
        print(f"{len(document['answers'])} answers agree with the rules; {GOLD.name} is {'STALE' if stale else 'up to date'}")
        return 1 if stale else 0
    GOLD.write_text(text, encoding="utf-8")
    print(f"wrote {GOLD.relative_to(ROOT)}: {len(document['answers'])} answers, all agree with the rules")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
