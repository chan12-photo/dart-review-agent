"""Cross-checked reading (design B, chosen 2026-10-08 after roadmap 2-2).

Two independent readers interpret the question:
- the keyword rules (dart_review/baseline.py), and
- the model, asked for one structured reading (no tools, no free text).

If both readings are the same, code runs the tool once and writes the answer
(dart_review/render.py). If they differ, nothing is answered: the user is
shown both readings and asked which one was meant, so a misreading by either
reader cannot become a confident wrong answer.

When only one reader produced a usable reading (policy decided 2026-10-08,
docs/reviews/roadmap_proposal_codex_response.ko.md section 5):
- rules only, because the model failed: nothing is answered. The rules alone
  misread a paraphrase in 2-2 (p06), and a model failure is a system fault.
- model only, because the rules could not read the question (no year, an
  abbreviation, a synonym): the answer starts with the model's reading in
  code-written words ("이렇게 이해했습니다: ..."), so a misreading is visible,
  and the path is counted separately in evaluation.
- explicit rules-only mode (``ask=None``, the CLI's --no-model): the rules
  answer alone, with a note saying so.

Both readers may refuse an account the tool does not cover ("unsupported");
a refusal is final only when both refuse (review B7/C1).

Before anything is shown, every number in the text is checked against the
tool results (roadmap 2-3); years may also come from the question and from
the readings being proposed. An answer with an ungrounded number is withheld.
"""

from __future__ import annotations

from datetime import date
import json
from typing import Any, Callable

from .accounts import ACCOUNTS
from .baseline import Reading, read
from .companies import DEV_COMPANIES
from .numbers import allowed_from, check_text, question_years, ungrounded
from .render import clarification_answer, period_text, structured_answer, unsupported_answer
from .tools import BASIS_CODES, PERIOD_KINDS, ToolArgumentError, execute_tool, find_company, parse_period, period_dict

READING_PROMPT_VERSION = "reading-v2"  # v2 (3-0b): unsupported action, reference date
ACTIONS = ("compare", "side_by_side", "clarify", "unsupported")

_PERIOD = {"type": "object", "properties": {"kind": {"type": "string", "enum": list(PERIOD_KINDS)},
                                            "year": {"type": "integer"},
                                            "month": {"type": "integer", "enum": [3, 6, 9, 12]}},
           "required": ["kind", "year", "month"], "additionalProperties": False}
READING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": list(ACTIONS)},
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

# A template: {reference_date} is filled in by reading_prompt(); contract hashes cover the template.
READING_SYSTEM_PROMPT = """너는 한국 상장사 재무 비교 질문을 해석한다. 답을 쓰지 말고, 질문이 무엇을 비교해 달라는지만 정해진 JSON으로 적는다.

- action: compare(한 기준·한 계정의 두 기간 비교), side_by_side(같은 기간의 연결 값과 별도 값을 나란히), clarify(질문이 두 가지 이상의 계정으로 읽혀 먼저 물어야 함, 예: "이익"은 영업이익일 수도 당기순이익일 수도 있다), unsupported(질문한 계정이 아래 여섯 계정 중 하나가 아님).
- unsupported: 질문의 계정이 여섯 계정과 다른 계정이면 고른다. 이름에 여섯 계정의 일부가 들어 있어도 다른 계정이면 unsupported다(예: 현금및현금성자산은 자산총계가 아니고, 이익잉여금은 당기순이익이 아니다). 비슷한 계정으로 바꿔 읽지 않는다. 이때 나머지 칸은 질문에서 읽은 대로 채운다.
- company: 질문의 회사 이름. basis: 연결 또는 별도(언급이 없으면 연결). account: revenue=매출액, operating_income=영업이익, net_income=당기순이익, operating_cash_flow=영업활동현금흐름, total_assets=자산총계, total_liabilities=부채총계.
- 기간: kind는 instant(재무상태표의 시점), quarter(그 분기 3개월), year_to_date(연초부터 누적, 연간은 month 12). month는 3, 6, 9, 12.
  - "N년 매출"은 N년 연간. "3분기 매출"·"7~9월"은 quarter, month 9. "3분기 누적"·"3분기까지"·"1~9월"·"9월까지 누적"은 year_to_date, month 9. "상반기"·"1~6월"은 year_to_date, month 6. "3분기말 자산"·"9월 말 자산"은 instant, month 9. 자산·부채의 연도만 있으면 그해 말(instant, month 12).
  - current_period는 비교하려는 나중 기간, base_period는 그 기준이 되는 앞 기간이다. "전년보다", "1년 전"은 같은 종류의 전년 기간, "직전 분기"는 바로 앞 분기다. 두 연도가 나오면 나중 연도가 current다.
- 기준 날짜는 {reference_date}이다. 질문에 연도가 없으면 이 날짜로 정한다: "올해"는 기준 날짜의 연도, "작년"·"지난해"는 그 전년, "재작년"은 2년 전이다.
- side_by_side면 current_period에 그 기간을 넣고 base_period는 같은 값으로 둔다. clarify면 clarify_accounts에 후보 계정을 모두 넣고, 나머지 칸은 질문에서 읽은 대로 채운다."""


def reading_prompt(reference_date: date) -> str:
    return READING_SYSTEM_PROMPT.replace("{reference_date}", reference_date.isoformat())


def reading_messages(question: str, reference_date: date) -> list[dict[str, str]]:
    return [{"role": "system", "content": reading_prompt(reference_date)}, {"role": "user", "content": question}]


class ReadingError(ValueError):
    pass


def _member(value: Any, allowed: Any) -> bool:
    """``value in allowed`` for a string only (a list or dict would be unhashable or never equal)."""
    return isinstance(value, str) and value in allowed


def parse_model_reading(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except ValueError:
        raise ReadingError("the reading is not JSON") from None
    if not isinstance(data, dict) or set(data) != set(READING_SCHEMA["required"]):
        raise ReadingError("the reading must have exactly the schema fields")
    # the schema is a request to the server, not a guarantee: check every type before use (review B2)
    if not _member(data["action"], ACTIONS):
        raise ReadingError(f"unknown action {data['action']!r}")
    if not isinstance(data["company"], str):
        raise ReadingError("company must be a string")
    if not _member(data["basis"], BASIS_CODES):
        raise ReadingError("basis must be 연결 or 별도")
    if not _member(data["account"], ACCOUNTS):
        raise ReadingError("account must be an account key")
    if not all(isinstance(data[field], dict) for field in ("current_period", "base_period")):
        raise ReadingError("periods must be objects")
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


def canonical(kind: str, arguments: dict[str, Any] | None, company: str, options: Any = ()) -> tuple | None:
    """A comparable form of a reading, or None when it is not usable.

    Two clarifying readings agree only when they offer the same candidate
    accounts (in any order); the periods they carry are placeholders and are
    not compared (review B5).
    """
    corp = _corp(company)
    if corp is None:
        return None
    if kind == "clarify":
        candidates = tuple(sorted({key for key in options if _member(key, ACCOUNTS)}))
        return ("clarify", corp, candidates) if len(candidates) >= 2 else None
    if kind == "unsupported":
        return ("unsupported", corp)
    if not isinstance(arguments, dict):
        return None
    if kind == "side_by_side":
        period = _period_key(arguments.get("period"))
        account = arguments.get("account")
        return ("side_by_side", corp, account, period) if period and _member(account, ACCOUNTS) else None
    current, base = _period_key(arguments.get("current_period")), _period_key(arguments.get("base_period"))
    if kind != "compare" or current is None or base is None or not _member(arguments.get("basis"), BASIS_CODES) \
            or not _member(arguments.get("account"), ACCOUNTS):
        return None
    return ("compare", corp, arguments["basis"], arguments["account"], current, base)


def model_to_reading(data: dict[str, Any]) -> Reading:
    company = data["company"]
    if data["action"] == "unsupported":
        return Reading("unsupported", {}, company)
    if data["action"] == "clarify":
        return Reading("clarify", company=company, options=tuple(data["clarify_accounts"]))
    if data["action"] == "side_by_side":
        return Reading("side_by_side", {"company": company, "account": data["account"], "period": data["current_period"]}, company)
    return Reading("compare", {"company": company, "basis": data["basis"], "account": data["account"],
                               "current_period": data["current_period"], "base_period": data["base_period"]}, company)


def describe(reading: Reading, with_company: bool = False) -> str:
    """One reading in words, with the base period relative to the current one where possible.

    ``with_company`` names the company, for when the two readings differ in it (review B5).
    """
    prefix = f"{reading.company}, " if with_company else ""
    return prefix + _describe(reading)


def _describe(reading: Reading) -> str:
    if reading.kind == "unsupported":
        term = (reading.arguments or {}).get("term")
        return f"다루지 않는 계정({term})을 묻는 질문" if term else "다루지 않는 계정을 묻는 질문"
    if reading.kind == "clarify":
        labels = [ACCOUNTS[key].label for key in reading.options if key in ACCOUNTS]
        return f"{'·'.join(labels)} 중 어느 것인지 먼저 확인해야 하는 질문" if labels else "계정을 먼저 확인해야 하는 질문"
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
    named = _corp(first.company) != _corp(second.company)
    question = (f"질문을 두 가지로 읽을 수 있습니다. ① {describe(first, named)} ② {describe(second, named)}. "
                "어느 쪽으로 볼까요?")
    return {"status": "되묻기", "company": company, "account": None, "values": [], "change": None, "change_pct": None,
            "answer": "답하기 전에 확인이 필요합니다. " + question, "clarifying_question": question}


def candidate_years(*readings: Reading | None) -> set[int]:
    """The years two readings propose. They may appear in a clarifying question, labeled as readings, never as facts."""
    years = set()
    for reading in readings:
        for name in ("current_period", "base_period", "period"):
            spec = (reading.arguments or {}).get(name) if reading else None
            if isinstance(spec, dict) and isinstance(spec.get("year"), int) and not isinstance(spec["year"], bool):
                years.add(spec["year"])
    return years


def ungrounded_in_text(text: str, seen: list[Any], question: str, proposed_years: Any = ()) -> list[str]:
    """Numbers in ``text`` that no successful tool result supports.

    Years may also come from the question and from the readings being
    proposed; amounts, rates, and receipts only from tool results.
    """
    allowed = allowed_from(*seen)
    allowed.years |= question_years(question) | set(proposed_years)
    return [mention.text for mention in ungrounded(check_text(text, allowed))]


def ungrounded_in_answer(answer: dict[str, Any], seen: list[Any], question: str, proposed_years: Any = ()) -> list[str]:
    """Roadmap 2-3: numbers in the text to be shown that no tool result supports."""
    text = answer["answer"] + "\n" + (answer.get("clarifying_question") or "")
    return ungrounded_in_text(text, seen, question, proposed_years)


def _company_name(reading: Reading) -> str:
    corp = _corp(reading.company)
    return DEV_COMPANIES[corp] if corp else reading.company


def crosscheck_turn(question: str, client: Any, record: dict[str, Any], ask: Callable[..., Any] | None,
                    reference_date: date | None = None) -> None:
    """Read ``question`` twice, compare, and fill ``record``. ``ask`` None is the explicit rules-only mode."""
    reference_date = reference_date or date.today()
    rule = read(question)
    readings: dict[str, Any] = {"rule": {"kind": rule.kind, "arguments": rule.arguments, "reason": rule.reason},
                                "model": None, "agree": None, "used": None, "reference_date": reference_date.isoformat()}
    record["readings"] = readings
    model: Reading | None = None
    if ask is not None:
        reply = ask(reading_messages(question, reference_date), schema=READING_SCHEMA)
        try:
            data = parse_model_reading(reply.content)
            model = model_to_reading(data)
            readings["model"] = {"kind": model.kind, "company": model.company, "arguments": model.arguments,
                                 "options": list(model.options)}
        except ReadingError as exc:
            readings["model_error"] = str(exc)
    rule_key = canonical(rule.kind, rule.arguments, rule.company, rule.options) if rule.kind != "unreadable" else None
    model_key = canonical(model.kind, model.arguments, model.company, model.options) if model else None
    header = note = None
    if ask is None:
        if not rule_key:
            readings["used"] = "none"
            record["no_result"] = True
            return
        chosen, readings["used"] = rule, "rules only (--no-model)"
        note = "참고: 모델 없이(--no-model) 규칙 해석 하나로만 확인한 답이다"
    elif rule_key and model_key:
        readings["agree"] = rule_key == model_key
        if not readings["agree"]:
            readings["used"] = "neither (asked back)"
            # the question names the model's periods: check it too (review B6/C2), with only
            # the readings' years allowed besides the question's, and no tool figures at all
            record["proposed_years"] = sorted(candidate_years(rule, model))
            answer = disagreement_answer(rule.company, rule, model)
            blocked = ungrounded_in_answer(answer, record["seen"], question, record["proposed_years"])
            if blocked:
                record["output_blocked"] = blocked
                record["no_result"] = True
                return
            record["answer"] = answer
            return
        chosen, readings["used"] = rule, "both"
    elif rule_key:
        # the model failed and the rules alone are not trusted with an answer (policy 2026-10-08)
        readings["used"] = "rule only (withheld)"
        record["withheld_reason"] = "모델 해석을 얻지 못해 답하지 않습니다 (규칙 해석 하나만으로는 답하지 않음)"
        record["no_result"] = True
        return
    elif model_key:
        chosen, readings["used"] = model, "model only"
        header = f"이렇게 이해했습니다: {describe(model)}."
        record["proposed_years"] = sorted(candidate_years(model))
    else:
        readings["used"] = "none"
        record["no_result"] = True
        return
    company = _company_name(chosen)
    if chosen.kind == "unsupported":
        answer = unsupported_answer(company, (rule.arguments or {}).get("term") if rule.kind == "unsupported" else None)
    elif chosen.kind == "clarify":
        answer = clarification_answer(company, list(chosen.options))
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
    if header:
        answer["answer"] = header + "\n" + answer["answer"]
    if note:
        answer["answer"] += "\n" + note
    blocked = ungrounded_in_answer(answer, record["seen"], question, record.get("proposed_years", ()))
    if blocked:
        record["output_blocked"] = blocked
        record["no_result"] = True
        return
    record["answer"] = answer
