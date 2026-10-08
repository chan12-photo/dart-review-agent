"""Write the factual part of an answer from verified tool results (no model involved).

Roadmap 1-5 showed the model reports structured fields correctly but writes
poor visible text, so every sentence carrying a number, a period, a basis, or
a status reason is produced here from the tool result. The model only adds an
optional short interpretation, checked separately (dart_review/agent.py).

Amounts are written down to 억 (truncated), which the number check accepts
as a truncation of the exact amount.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from .accounts import ACCOUNTS

SIDE_BY_SIDE = "나란히 표시"


def format_won(amount: int) -> str:
    """333,605,938,000,000 -> "333조 6,059억 원" (truncated below the last unit shown)."""
    sign = "-" if amount < 0 else ""
    value = abs(amount)
    if value >= 10 ** 12:
        jo, eok = divmod(value // 10 ** 8, 10 ** 4)
        return f"{sign}{jo:,}조 {eok:,}억 원" if eok else f"{sign}{jo:,}조 원"
    if value >= 10 ** 8:
        return f"{sign}{value // 10 ** 8:,}억 원"
    if value >= 10 ** 4:
        return f"{sign}{value // 10 ** 4:,}만 원"
    return f"{sign}{value:,}원"


def format_amount(amount: int, currency: str | None) -> str:
    """An amount in won only when the filing says KRW; otherwise the exact figure with its currency, never called 원."""
    if currency == "KRW":
        return format_won(amount)
    return f"{amount:,} ({currency} 단위)" if currency else f"{amount:,} (통화 미확인)"


def _common_currency(*facts: dict[str, Any] | None) -> str | None:
    currencies = {fact.get("currency") for fact in facts if fact}
    return currencies.pop() if len(currencies) == 1 else None


def period_text(period: dict[str, Any]) -> str:
    """A tool period ({start, end, label}) in plain Korean that names its kind."""
    end = date.fromisoformat(period["end"])
    if period.get("start") is None:
        return f"{end.year}년 {end.month}월 {end.day}일 시점"
    start = date.fromisoformat(period["start"])
    months = (end.year - start.year) * 12 + end.month - start.month + 1
    if start.month == 1 and start.year == end.year:
        if months == 12:
            return f"{end.year}년 연간(1~12월)"
        if months == 6:
            return f"{end.year}년 상반기(1~6월 누적)"
        if months == 3:
            return f"{end.year}년 1분기(1~3월)"
        return f"{end.year}년 1~{end.month}월 누적"
    if months == 3 and end.month % 3 == 0:
        return f"{end.year}년 {end.month // 3}분기({start.month}~{end.month}월, 3개월)"
    return period.get("label", f"{start.isoformat()}~{end.isoformat()}")


def _subject(result: dict[str, Any], basis: str | None = None) -> str:
    return f"{result['company']} {basis or result['basis']} 기준 {result['account_label']}"


def _direction_sentence(result: dict[str, Any], base_period: str) -> str:
    change, rate, direction = result["change"], result["change_pct"], result["direction"]
    amount = format_amount(abs(change), _common_currency(result.get("current"), result.get("base")))
    if rate is not None:
        return f"{base_period}보다 {amount}({rate.lstrip('-')}%) {direction}했습니다." \
            if direction in ("증가", "감소") else f"{base_period}과 같습니다(변동 없음)."
    if direction in ("흑자 전환", "적자 전환", "적자 축소", "적자 확대", "적자 지속"):
        return (f"{base_period}보다 {amount} {'늘어' if change > 0 else '줄어'} {direction}했습니다. "
                "기준 값이 0 이하이거나 부호가 바뀌어 변화율은 계산하지 않습니다.")
    return (f"{base_period}보다 {amount} {direction}했습니다. "
            "기준 값이 0 이하이거나 부호가 바뀌어 변화율은 계산하지 않습니다.")


def _alternative(result: dict[str, Any]) -> str:
    """A comparable condition to offer when the requested one is not provided."""
    reasons = " ".join(result.get("reasons", []))
    current = result.get("requested", {}).get("current")
    if not current:
        return ""
    end = date.fromisoformat(current["end"])
    if "누적 값만" in reasons:
        return f"대신 {end.year}년 1~{end.month}월 누적처럼 연초부터의 누적 기간끼리는 비교할 수 있습니다."
    if "4분기" in reasons:
        return f"대신 {end.year}년 연간 값끼리는 비교할 수 있습니다."
    return ""


def render_comparison(result: dict[str, Any]) -> str:
    """The factual answer for a compare_values result."""
    status = result["status"]
    requested = result.get("requested", {})
    if status in ("비교 가능", "확인 필요"):
        facts = [(period_text(fact["period"]), fact) for fact in (result["current"], result["base"])]
        lines = []
        if status == "확인 필요":
            lines.append("확인이 필요합니다. " + " ".join(f"{reason}." for reason in result["reasons"]))
        # a value under review may have no amount (several candidate rows): say so, never format a missing number
        known = [f"{period} {format_amount(fact['amount'], fact.get('currency'))}" for period, fact in facts
                 if fact.get("amount") is not None]
        unknown = [period for period, fact in facts if fact.get("amount") is None]
        if known:
            lines.append(f"{_subject(result)}: {', '.join(known)}.")
        if unknown:
            lines.append(f"{_subject(result)}: {', '.join(unknown)} 값은 확정하지 못했습니다.")
        if result.get("change") is not None:
            lines.append(_direction_sentence(result, facts[1][0]))
        # the rate note repeats the direction sentence above, so it is left out
        lines += [f"참고: {note}" for note in result.get("notes", []) if "변화율을 계산하지 않는다" not in note]
        return "\n".join(lines)
    periods = " / ".join(period_text(requested[role]) for role in ("current", "base") if role in requested)
    if status == "데이터 없음":
        return (f"{_subject(result)} ({periods}): OpenDART가 이 기간의 재무제표를 제공하지 않아 조회 결과가 없습니다. "
                "오류가 아니라 자료가 없는 것입니다.")
    reasons = " ".join(f"{reason}." for reason in result.get("reasons", []))
    text = f"{_subject(result)} ({periods})는 비교하지 않습니다. 이유: {reasons}"
    alternative = _alternative(result)
    return f"{text} {alternative}".strip()


def render_side_by_side(result: dict[str, Any]) -> str:
    period = period_text(result["period"])
    subject = f"{result['company']} {period} {result['account_label']}"
    if result["status"] != SIDE_BY_SIDE:
        values = ", ".join(f"{value['basis']} {format_amount(value['amount'], value.get('currency'))}" for value in result.get("values", [])
                           if value and value.get("amount") is not None)
        reasons = " ".join(f"{reason}." for reason in result.get("reasons", []))
        return f"{subject}: {values}. {result['status']}: {reasons}".replace(": .", ":")
    consolidated, separate = result["values"]
    difference, currency = result["difference"], _common_currency(consolidated, separate)
    bigger = "큽니다" if difference >= 0 else "작습니다"
    return (f"{subject}: 연결 {format_amount(consolidated['amount'], currency)}, 별도 {format_amount(separate['amount'], currency)}.\n"
            f"연결이 별도보다 {format_amount(abs(difference), currency)} {bigger}. 같은 기간·같은 통화에서 집계 범위가 다른 데서 오는 차이이며, "
            "시간에 따른 변화가 아닙니다.")


def render_result(result: dict[str, Any]) -> str:
    return render_side_by_side(result) if result.get("tool") == "side_by_side" else render_comparison(result)


def clarifying_question(accounts: list[str]) -> str:
    labels = [ACCOUNTS[key].label for key in accounts if key in ACCOUNTS]
    if len(labels) >= 2:
        return f"{', '.join(labels[:-1])}과 {labels[-1]} 중 어느 것을 비교할까요?"
    return "어떤 계정(예: 매출액, 영업이익, 당기순이익)을 비교할지 알려 주세요."


def answer_values(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The structured values behind a rendered answer (only when it reports amounts)."""
    if result.get("tool") == "side_by_side":
        facts = result.get("values", []) if result["status"] == SIDE_BY_SIDE else []
    elif result["status"] in ("비교 가능", "확인 필요"):
        facts = [result["current"], result["base"]]
    else:
        facts = []
    return [{"basis": fact["basis"], "start": fact["period"]["start"], "end": fact["period"]["end"], "amount": fact["amount"]}
            for fact in facts]


def structured_answer(result: dict[str, Any], explanation: str | None = None) -> dict[str, Any]:
    """The full answer (EVAL_DESIGN section 2) from one tool result and an optional checked explanation."""
    text = render_result(result)
    if explanation:
        text += "\n\n해석(모델): " + explanation
    side = result.get("tool") == "side_by_side"
    reports_change = not side and result["status"] in ("비교 가능", "확인 필요")
    return {"status": result["status"], "company": result["company"], "account": result["account"],
            "values": answer_values(result), "change": result["change"] if reports_change else None,
            "change_pct": result["change_pct"] if reports_change else None, "answer": text,
            "clarifying_question": None}


def clarification_answer(company: str, accounts: list[str]) -> dict[str, Any]:
    question = clarifying_question(accounts)
    return {"status": "되묻기", "company": company, "account": None, "values": [], "change": None,
            "change_pct": None, "answer": "질문이 여러 계정으로 읽혀서 먼저 확인하겠습니다. " + question,
            "clarifying_question": question}


def unsupported_answer(company: str, term: str | None = None) -> dict[str, Any]:
    """A refusal for an account this tool does not cover (review B7/C1)."""
    supported = ", ".join(account.label for account in ACCOUNTS.values())
    what = f": {term}" if term else ""
    return {"status": "비교 불가", "company": company, "account": None, "values": [], "change": None,
            "change_pct": None,
            "answer": f"{company}: 이 도구가 다루지 않는 계정이라 답하지 않습니다{what}. 다룰 수 있는 계정은 {supported}입니다.",
            "clarifying_question": None}


def markdown_report(answer: dict[str, Any], result: dict[str, Any] | None) -> str:
    """A Markdown report: verification status, a table of the values with their sources, and the confirmed facts.

    Every figure comes from the tool result; there is no free-text interpretation in this report.
    """
    lines = [f"## {answer['company']} {result['account_label'] if result else ''}".rstrip(), "",
             f"**검증 상태:** {answer['status']}", ""]
    facts = []
    if result is not None:
        if result.get("tool") == "side_by_side":
            facts = [(value["basis"], value) for value in result.get("values", []) if value and value.get("amount") is not None]
        else:
            facts = [(label, result[key]) for label, key in (("비교 기간", "current"), ("기준 기간", "base"))
                     if result.get(key) and result[key].get("amount") is not None]
    if facts:
        won = all(fact.get("currency") == "KRW" for _, fact in facts)  # otherwise each amount carries its currency
        lines += [f"| 구분 | 기준 | 기간 | {'금액(원)' if won else '금액'} | 보고서 | 접수번호 |", "|---|---|---|---:|---|---|"]
        for label, fact in facts:
            amount = f"{fact['amount']:,}" if won else f"{fact['amount']:,} {fact.get('currency') or '(통화 미확인)'}"
            lines.append(f"| {label} | {fact['basis']} | {period_text(fact['period'])} | {amount} | {fact['report']} | {fact['rcept_no']} |")
        if result.get("tool") != "side_by_side" and result.get("change") is not None:
            rate = f"{result['change_pct']}%" if result.get("change_pct") is not None else "계산하지 않음"
            currency = _common_currency(result.get("current"), result.get("base"))
            change = f"{result['change']:,}원" if currency == "KRW" else f"{result['change']:,} {currency or '(통화 미확인)'}"
            lines += ["", f"**변화:** {change} ({rate}, {result['direction']})"]
        lines.append("")
    lines += ["### 확정 사실 (도구 결과로 작성)", "", answer["answer"]]
    if answer.get("clarifying_question"):
        lines += ["", f"**확인 질문:** {answer['clarifying_question']}"]
    return "\n".join(lines) + "\n"
