"""Cross-checked reading (design B, chosen 2026-10-08 after roadmap 2-2).

Two independent readers interpret the question:
- the keyword rules (dart_review/baseline.py), and
- the model, asked for one structured reading (no tools, no free text).

If both readings are the same, code runs the tool once and writes the answer
(dart_review/render.py). If they differ, nothing is answered: the user is
shown both readings and asked which one was meant, so a misreading by either
reader cannot become a confident wrong answer. If only one reader produced a
reading, the answer is given from it with a visible note.

Before anything is shown, every number in the answer text is checked against
the tool results (roadmap 2-3); an answer with an ungrounded number is
withheld.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from .accounts import ACCOUNTS
from .baseline import Reading, read
from .numbers import allowed_from, check_text, question_years, ungrounded
from .render import clarification_answer, period_text, structured_answer
from .tools import BASIS_CODES, PERIOD_KINDS, ToolArgumentError, execute_tool, find_company, parse_period, period_dict

READING_PROMPT_VERSION = "reading-v1"

_PERIOD = {"type": "object", "properties": {"kind": {"type": "string", "enum": list(PERIOD_KINDS)},
                                            "year": {"type": "integer"},
                                            "month": {"type": "integer", "enum": [3, 6, 9, 12]}},
           "required": ["kind", "year", "month"], "additionalProperties": False}
READING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["compare", "side_by_side", "clarify"]},
        "company": {"type": "string"},
        "basis": {"type": "string", "enum": list(BASIS_CODES)},
        "account": {"type": "string", "enum": list(ACCOUNTS)},
        "current_period": _PERIOD,
        "base_period": _PERIOD,
        "clarify_accounts": {"type": "array", "items": {"type": "string", "enum": list(ACCOUNTS)}},
    },
    "required": ["action", "company", "basis", "account", "current_period", "base_period", "clarify_accounts"],
    "additionalProperties": False,
}

READING_SYSTEM_PROMPT = """너는 한국 상장사 재무 비교 질문을 해석한다. 답을 쓰지 말고, 질문이 무엇을 비교해 달라는지만 정해진 JSON으로 적는다.

- action: compare(한 기준·한 계정의 두 기간 비교), side_by_side(같은 기간의 연결 값과 별도 값을 나란히), clarify(질문이 두 가지 이상의 계정으로 읽혀 먼저 물어야 함, 예: "이익"은 영업이익일 수도 당기순이익일 수도 있다).
- company: 질문의 회사 이름. basis: 연결 또는 별도(언급이 없으면 연결). account: revenue=매출액, operating_income=영업이익, net_income=당기순이익, operating_cash_flow=영업활동현금흐름, total_assets=자산총계, total_liabilities=부채총계.
- 기간: kind는 instant(재무상태표의 시점), quarter(그 분기 3개월), year_to_date(연초부터 누적, 연간은 month 12). month는 3, 6, 9, 12.
  - "N년 매출"은 N년 연간. "3분기 매출"·"7~9월"은 quarter, month 9. "3분기 누적"·"3분기까지"·"1~9월"·"9월까지 누적"은 year_to_date, month 9. "상반기"·"1~6월"은 year_to_date, month 6. "3분기말 자산"·"9월 말 자산"은 instant, month 9. 자산·부채의 연도만 있으면 그해 말(instant, month 12).
  - current_period는 비교하려는 나중 기간, base_period는 그 기준이 되는 앞 기간이다. "전년보다", "1년 전"은 같은 종류의 전년 기간, "직전 분기"는 바로 앞 분기다. 두 연도가 나오면 나중 연도가 current다.
- side_by_side면 current_period에 그 기간을 넣고 base_period는 같은 값으로 둔다. clarify면 clarify_accounts에 후보 계정을 모두 넣고, 나머지 칸은 질문에서 읽은 대로 채운다."""


class ReadingError(ValueError):
    pass


def parse_model_reading(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except ValueError:
        raise ReadingError("the reading is not JSON") from None
    if not isinstance(data, dict) or set(data) != set(READING_SCHEMA["required"]):
        raise ReadingError("the reading must have exactly the schema fields")
    if data["action"] not in ("compare", "side_by_side", "clarify"):
        raise ReadingError(f"unknown action {data['action']!r}")
    accounts = data["clarify_accounts"]
    if not isinstance(accounts, list) or not all(isinstance(key, str) and key in ACCOUNTS for key in accounts):
        raise ReadingError("clarify_accounts must list account keys")
    return data


def _period_key(spec: Any) -> tuple | None:
    try:
        period = parse_period(spec, "period")
    except ToolArgumentError:
        return None
    return (period.end.isoformat(), period.months)


def _corp(name: Any) -> str | None:
    try:
        return find_company(name)
    except ToolArgumentError:
        return None


def canonical(kind: str, arguments: dict[str, Any] | None, company: str) -> tuple | None:
    """A comparable form of a reading, or None when it is not usable."""
    corp = _corp(company)
    if corp is None:
        return None
    if kind == "clarify":
        return ("clarify", corp)
    if not isinstance(arguments, dict):
        return None
    if kind == "side_by_side":
        period = _period_key(arguments.get("period"))
        return ("side_by_side", corp, arguments.get("account"), period) if period else None
    current, base = _period_key(arguments.get("current_period")), _period_key(arguments.get("base_period"))
    if kind != "compare" or current is None or base is None or arguments.get("basis") not in BASIS_CODES \
            or arguments.get("account") not in ACCOUNTS:
        return None
    return ("compare", corp, arguments["basis"], arguments["account"], current, base)


def model_to_reading(data: dict[str, Any]) -> Reading:
    company = data["company"]
    if data["action"] == "clarify":
        return Reading("clarify", company=company, options=tuple(data["clarify_accounts"]))
    if data["action"] == "side_by_side":
        return Reading("side_by_side", {"company": company, "account": data["account"], "period": data["current_period"]}, company)
    return Reading("compare", {"company": company, "basis": data["basis"], "account": data["account"],
                               "current_period": data["current_period"], "base_period": data["base_period"]}, company)


def describe(reading: Reading) -> str:
    """One reading in words, with the base period relative to the current one where possible."""
    if reading.kind == "clarify":
        return "계정을 먼저 확인해야 하는 질문"
    arguments = reading.arguments
    label = ACCOUNTS.get(arguments.get("account"), None)
    label = label.label if label else "계정"
    if reading.kind == "side_by_side":
        return f"{period_text(period_dict(parse_period(arguments['period'], 'period')))} {label}의 연결·별도 값을 나란히 보기"
    current, base = arguments["current_period"], arguments["base_period"]
    current_text = period_text(period_dict(parse_period(current, "current_period")))
    if base["kind"] == current["kind"] and base["month"] == current["month"] and base["year"] == current["year"] - 1:
        relation = "전년 같은 기간과"
    elif base["kind"] == current["kind"] == "quarter" and (
            (base["year"], base["month"]) == ((current["year"], current["month"] - 3) if current["month"] > 3 else (current["year"] - 1, 12))):
        relation = "직전 분기와"
    else:
        relation = f"{period_text(period_dict(parse_period(base, 'base_period')))}과"
    return f"{arguments['basis']} 기준 {label}, {current_text}을 {relation} 비교"


def disagreement_answer(company: str, first: Reading, second: Reading) -> dict[str, Any]:
    question = f"질문을 두 가지로 읽을 수 있습니다. ① {describe(first)} ② {describe(second)}. 어느 쪽으로 볼까요?"
    return {"status": "되묻기", "company": company, "account": None, "values": [], "change": None, "change_pct": None,
            "answer": "답하기 전에 확인이 필요합니다. " + question, "clarifying_question": question}


def ungrounded_in_answer(answer: dict[str, Any], seen: list[Any], question: str) -> list[str]:
    """Roadmap 2-3: numbers in the text to be shown that no tool result supports."""
    allowed = allowed_from(*seen)
    allowed.years |= question_years(question)
    text = answer["answer"] + "\n" + (answer.get("clarifying_question") or "")
    return [mention.text for mention in ungrounded(check_text(text, allowed))]


def crosscheck_turn(question: str, client: Any, record: dict[str, Any], ask: Callable[..., Any]) -> None:
    rule = read(question)
    readings: dict[str, Any] = {"rule": {"kind": rule.kind, "arguments": rule.arguments, "reason": rule.reason},
                                "model": None, "agree": None, "used": None}
    record["readings"] = readings
    model: Reading | None = None
    reply = ask([{"role": "system", "content": READING_SYSTEM_PROMPT}, {"role": "user", "content": question}],
                schema=READING_SCHEMA)
    try:
        data = parse_model_reading(reply.content)
        model = model_to_reading(data)
        readings["model"] = {"kind": model.kind, "arguments": model.arguments, "options": list(model.options)}
    except ReadingError as exc:
        readings["model_error"] = str(exc)
    rule_key = canonical(rule.kind, rule.arguments, rule.company) if rule.kind != "unreadable" else None
    model_key = canonical(model.kind, model.arguments, model.company) if model else None
    note = None
    if rule_key and model_key:
        readings["agree"] = rule_key == model_key
        if not readings["agree"]:
            readings["used"] = "neither (asked back)"
            record["answer"] = disagreement_answer(rule.company, rule, model)
            return
        chosen, readings["used"] = rule, "both"
    elif rule_key or model_key:
        chosen = rule if rule_key else model
        readings["used"] = "rule only" if rule_key else "model only"
        note = ("참고: 모델의 해석을 얻지 못해 규칙 해석 하나로만 확인한 답이다" if rule_key
                else "참고: 규칙으로 읽지 못해 모델 해석 하나로만 확인한 답이다")
    else:
        record["no_result"] = True
        return
    if chosen.kind == "clarify":
        options = list(rule.options or (model.options if model else ())) or ["operating_income", "net_income"]
        answer = clarification_answer(chosen.company, options)
    else:
        name = "side_by_side" if chosen.kind == "side_by_side" else "compare_values"
        result = execute_tool(client, name, chosen.arguments)
        record["tool_call_count"] += 1
        record["tool_calls"].append({"raw": None, "name": name, "arguments": chosen.arguments, "result": result})
        record["seen"].append(result)
        if "error" in result:
            record["no_result"] = True
            return
        answer = structured_answer(result)
    if note:
        answer["answer"] += "\n" + note
    blocked = ungrounded_in_answer(answer, record["seen"], question)
    if blocked:
        record["output_blocked"] = blocked
        record["no_result"] = True
        return
    record["answer"] = answer
