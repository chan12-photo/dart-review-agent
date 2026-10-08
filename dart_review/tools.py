"""Tools the model can call. Each returns plain JSON data built only from the rules and the cache.

The model never sees raw OpenDART rows: periods, comparability, and changes
come from the rule code, and every number the model may repeat is in these
results (docs/EVAL_DESIGN.ko.md section 4).
"""

from __future__ import annotations

import json
from typing import Any

from .accounts import ACCOUNTS, NAME_CONFLICT
from .client import DartAPIError, DartClient, DartTransportError, NotCached
from .client import NO_DATA as NO_DATA_STATUS
from .company_names import resolve_company
from .companies import REPORT_CODES, supported_companies
from .compare import NEEDS_REVIEW, NO_DATA, NOT_COMPARABLE, Comparison, compare, find_restatements
from .facts import Fact, fact_from_response, is_ambiguous
from .periods import Period, PeriodNotProvided, Source, column_periods, instant, own_source, quarter, year_to_date
from .review import review_change

BASIS_CODES = {"연결": "CFS", "별도": "OFS"}
BASIS_NAMES = {code: name for name, code in BASIS_CODES.items()}
PERIOD_KINDS = {"instant": instant, "quarter": quarter, "year_to_date": year_to_date}
SIDE_BY_SIDE = "나란히 표시"
LOOKED_UP = "값 확인"  # EVAL_DESIGN 12.1
NOT_PROVIDED = "조회 불가"
DIFFERENCE_MEANING = "연결 − 별도: 같은 시점·같은 통화의 집계 범위 차이이며 시간에 따른 변화가 아니다"

_PERIOD_PARAMETER = {
    "type": "object",
    "additionalProperties": False,
    "description": "kind: instant(재무상태표의 시점), quarter(그 분기 3개월), year_to_date(연초부터 누적; 연간은 month=12)",
    "properties": {
        "kind": {"type": "string", "enum": list(PERIOD_KINDS)},
        "year": {"type": "integer", "minimum": 1990, "maximum": 2100},
        "month": {"type": "integer", "enum": [3, 6, 9, 12]},
    },
    "required": ["kind", "year", "month"],
}
_COMMON = {
    "company": {"type": "string", "description": "회사 이름 (예: 삼성전자)"},
    "account": {"type": "string", "enum": list(ACCOUNTS),
                "description": ", ".join(f"{key}={account.label}" for key, account in ACCOUNTS.items())},
}
TOOL_SPECS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "compare_values",
        "description": "한 회사·한 기준(연결 또는 별도)·한 계정의 두 기간 값을 비교 가능성 규칙에 따라 비교한다",
        "parameters": {"type": "object", "properties": {
            **_COMMON,
            "basis": {"type": "string", "enum": list(BASIS_CODES)},
            "current_period": _PERIOD_PARAMETER,
            "base_period": {**_PERIOD_PARAMETER, "description": "비교 기준이 되는 앞선 기간. " + _PERIOD_PARAMETER["description"]},
        }, "required": ["company", "basis", "account", "current_period", "base_period"], "additionalProperties": False},
    }},
    {"type": "function", "function": {
        "name": "side_by_side",
        "description": "한 기간의 연결 값과 별도 값을 나란히 보여 준다(시간 변화 비교가 아니다)",
        "parameters": {"type": "object", "properties": {**_COMMON, "period": _PERIOD_PARAMETER},
                       "required": ["company", "account", "period"], "additionalProperties": False},
    }},
]


class ToolArgumentError(ValueError):
    pass


def find_company(name: Any) -> str:
    """The supported company ``name`` means, by the same longest-name rule the readers use (EVAL_DESIGN 12.3)."""
    if not isinstance(name, str) or not name.strip():
        raise ToolArgumentError("company는 회사 이름 문자열이어야 한다")
    match = resolve_company(name)
    if match.kind == "company":
        return match.corp_code
    if match.kind == "sealed":
        raise ToolArgumentError(f"{name}은 개발 중 조회하지 않는 평가용 회사다")
    if match.kind == "group":
        raise ToolArgumentError(f"{name}은 여러 회사일 수 있다 (지원: {', '.join(supported_companies().values())})")
    raise ToolArgumentError(f"지원하지 않는 회사다: {name} (지원: {', '.join(supported_companies().values())})")


def parse_period(spec: Any, field: str) -> Period:
    if not isinstance(spec, dict) or set(spec) != {"kind", "year", "month"}:
        raise ToolArgumentError(f"{field}는 kind, year, month를 가진 객체여야 한다")
    kind, year, month = spec["kind"], spec["year"], spec["month"]
    if not isinstance(kind, str) or kind not in PERIOD_KINDS:
        raise ToolArgumentError(f"{field}.kind는 {', '.join(PERIOD_KINDS)} 중 하나여야 한다")
    if isinstance(year, bool) or not isinstance(year, int) or not 1990 <= year <= 2100:
        raise ToolArgumentError(f"{field}.year는 연도 정수여야 한다")
    if not isinstance(month, int) or isinstance(month, bool) or month not in (3, 6, 9, 12):
        raise ToolArgumentError(f"{field}.month는 3, 6, 9, 12 중 하나여야 한다")
    return PERIOD_KINDS[kind](year, month)


def _account(key: Any) -> str:
    if not isinstance(key, str) or key not in ACCOUNTS:
        raise ToolArgumentError(f"account는 {', '.join(ACCOUNTS)} 중 하나여야 한다")
    return key


def period_dict(period: Period) -> dict[str, Any]:
    return {"start": period.start.isoformat() if period.start else None, "end": period.end.isoformat(),
            "label": period.label()}


def fact_dict(fact: Fact | None) -> dict[str, Any] | None:
    if fact is None:
        return None
    return {"basis": BASIS_NAMES[fact.fs_div], "period": period_dict(fact.period), "amount": fact.amount,
            "currency": fact.currency, "report": f"{fact.source.year}년 {REPORT_CODES[fact.source.report_code]}",
            "rcept_no": fact.rcept_no, "account_nm": fact.account_nm}


def _comparison_dict(result: Comparison) -> dict[str, Any]:
    return {"status": result.status, "reasons": list(result.reasons), "notes": list(result.notes),
            "current": fact_dict(result.current), "base": fact_dict(result.base), "change": result.change,
            "change_pct": str(result.change_pct) if result.change_pct is not None else None,
            "direction": result.direction}


def compare_values(client: DartClient, company: Any, basis: Any, account: Any,
                   current_period: Any, base_period: Any) -> dict[str, Any]:
    corp_code = find_company(company)
    if not isinstance(basis, str) or basis not in BASIS_CODES:
        raise ToolArgumentError("basis는 연결 또는 별도여야 한다")
    key = _account(account)
    current, base = parse_period(current_period, "current_period"), parse_period(base_period, "base_period")
    result = review_change(client, corp_code, BASIS_CODES[basis], key, current, base)
    return {"tool": "compare_values", "company": supported_companies()[corp_code], "basis": basis, "account": key,
            "account_label": ACCOUNTS[key].label,
            "requested": {"current": period_dict(current), "base": period_dict(base)},
            **_comparison_dict(result)}


def side_by_side(client: DartClient, company: Any, account: Any, period: Any) -> dict[str, Any]:
    corp_code = find_company(company)
    key = _account(account)
    wanted = parse_period(period, "period")
    output: dict[str, Any] = {"tool": "side_by_side", "company": supported_companies()[corp_code], "account": key,
                              "account_label": ACCOUNTS[key].label, "period": period_dict(wanted)}
    try:
        source = own_source(wanted, ACCOUNTS[key].statements[0])
    except PeriodNotProvided as exc:
        return {**output, "status": NOT_COMPARABLE, "reasons": [str(exc)], "values": [], "difference": None}
    facts = [fact_from_response(client.financial_statements(corp_code, source.year, source.report_code, code),
                                key, source.column) for code in ("CFS", "OFS")]
    if not all(fact.available for fact in facts):
        reasons = [note for fact in facts if not fact.available for note in fact.notes]
        return {**output, "status": NO_DATA, "reasons": reasons, "values": [fact_dict(f) for f in facts], "difference": None}
    # the rules refuse a CFS/OFS change; the plain scope difference needs the
    # same company, account, period, and a confirmed common currency
    rule = compare(facts[0], facts[1])
    review = [note for fact in facts if fact.resolved_by == NAME_CONFLICT for note in fact.notes]
    currencies = [fact.currency for fact in facts]
    if not all(currencies):
        review.append("통화가 확인되지 않아 차이를 계산하지 않았다")
    elif currencies[0] != currencies[1]:
        review.append(f"통화가 달라({currencies[0]}, {currencies[1]}) 차이를 계산하지 않았다")
    if review:
        return {**output, "status": NEEDS_REVIEW, "reasons": review, "values": [fact_dict(fact) for fact in facts],
                "difference": None, "rule_status_for_change": rule.status}
    return {**output, "status": SIDE_BY_SIDE, "values": [fact_dict(fact) for fact in facts],
            "difference": facts[0].amount - facts[1].amount, "difference_meaning": DIFFERENCE_MEANING,
            "rule_status_for_change": rule.status}


def lookup_value(client: DartClient, company: Any, basis: Any, account: Any, period: Any) -> dict[str, Any]:
    """One value as filed in the report whose current period it is, checked against the next year's report.

    EVAL_DESIGN 12.2: if the same kind of report a year later presents the
    same period, its figure is read too; a different figure (a restatement)
    makes the result 확인 필요 with both figures. When that report is not
    available the result says the check was not made.
    """
    corp_code = find_company(company)
    if not isinstance(basis, str) or basis not in BASIS_CODES:
        raise ToolArgumentError("basis는 연결 또는 별도여야 한다")
    key = _account(account)
    wanted = parse_period(period, "period")
    sj_div = ACCOUNTS[key].statements[0]
    output: dict[str, Any] = {"tool": "lookup_value", "company": supported_companies()[corp_code], "basis": basis, "account": key,
                              "account_label": ACCOUNTS[key].label, "period": period_dict(wanted),
                              "value": None, "later": None, "reasons": [], "notes": []}
    try:
        source = own_source(wanted, sj_div)
    except PeriodNotProvided as exc:
        return {**output, "status": NOT_PROVIDED, "reasons": [str(exc)]}

    def read(source: Source) -> Fact:
        response = client.financial_statements(corp_code, source.year, source.report_code, BASIS_CODES[basis])
        return fact_from_response(response, key, source.column)

    fact = read(source)
    output["value"] = fact_dict(fact)
    if is_ambiguous(fact):
        return {**output, "status": NEEDS_REVIEW, "reasons": list(fact.notes)}
    if not fact.available:
        return {**output, "status": NO_DATA, "reasons": list(fact.notes) or [f"{wanted.label()} 값이 없다"]}
    reasons = [note for note in fact.notes if fact.resolved_by == NAME_CONFLICT]
    notes = [note for note in fact.notes if fact.resolved_by != NAME_CONFLICT]
    if not fact.currency:
        reasons.append("통화가 확인되지 않았다")
    later_year = source.year + 1
    later_column = next((column for column, covered in column_periods(later_year, source.report_code, sj_div).items()
                         if covered == wanted and column not in ("thstrm", "thstrm_add")), None)
    later_label = f"{later_year}년 {REPORT_CODES[source.report_code]}"
    if later_column is None:
        notes.append("이후 보고서의 재작성 여부는 확인하지 않았다 (같은 기간을 다시 싣는 다음 해 보고서가 없음)")
    else:
        try:
            later = read(Source(later_year, source.report_code, later_column))
        except NotCached:
            later = None
        if later is None or not later.available or later.resolved_by == NAME_CONFLICT or is_ambiguous(later):
            notes.append(f"이후 보고서의 재작성 여부는 확인하지 않았다 ({later_label}를 쓸 수 없음)")
        else:
            output["later"] = fact_dict(later)
            restated = find_restatements([fact, later])
            if later.currency != fact.currency:  # Codex 3-1 first review 6: never "일치" across currencies
                reasons.append(f"{later_label}의 같은 기간 값과 통화가 달라({fact.currency}, {later.currency}) 비교하지 못했다")
            elif restated:
                reasons += [item.describe() for item in restated]
            else:
                notes.append(f"{later_label}의 같은 기간 값과 일치한다")
    status = NEEDS_REVIEW if reasons else LOOKED_UP
    return {**output, "status": status, "reasons": reasons, "notes": notes}


TOOLS = {"compare_values": compare_values, "side_by_side": side_by_side, "lookup_value": lookup_value}
# Not offered to the 2-1 agent (its tool list, TOOL_SPECS, is unchanged); the cross-check calls it directly.
LOOKUP_SPEC: dict[str, Any] = {"type": "function", "function": {
    "name": "lookup_value",
    "description": "한 회사·한 기준·한 계정의 한 기간 값을 그 기간 보고서에서 조회한다",
    "parameters": {"type": "object", "properties": {**_COMMON, "basis": {"type": "string", "enum": list(BASIS_CODES)},
                                                    "period": _PERIOD_PARAMETER},
                   "required": ["company", "basis", "account", "period"], "additionalProperties": False},
}}


def execute_tool(client: DartClient, name: str, arguments: Any) -> dict[str, Any]:
    """Run a tool call from the model. Bad calls come back as an error result the model can read."""
    if not isinstance(name, str) or name not in TOOLS:
        return {"error": "알 수 없는 도구다"}  # the name is not echoed: an error must not carry the model's text
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return {"error": "도구 인자가 JSON이 아니다"}
    if not isinstance(arguments, dict):
        return {"error": "도구 인자는 객체여야 한다"}
    required = next(spec for spec in [*TOOL_SPECS, LOOKUP_SPEC] if spec["function"]["name"] == name)["function"]["parameters"]["required"]
    if not all(isinstance(key, str) for key in arguments) or set(arguments) != set(required):
        return {"error": f"{name}의 인자는 정확히 {', '.join(required)}이다"}
    try:
        return TOOLS[name](client, **arguments)
    except ToolArgumentError as exc:
        return {"error": str(exc)}
    except NotCached:
        return {"error": "이 보고서는 오프라인 캐시에 없다 (평가는 캐시로만 실행한다)"}
    except (DartAPIError, DartTransportError) as exc:
        return {"error": f"OpenDART 조회 실패: {exc}"}
