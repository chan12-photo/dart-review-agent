"""Rule-based baseline (roadmap 2-2): keyword rules read the question, fixed steps answer it. No model.

The agent has to beat this to justify the model (SCOPE section 7). The rules
are general readings of the defaults table in docs/GOLD_RULES.ko.md section
2, with no per-question exceptions:

1. Company: a supported company name in the text (spaces ignored).
2. Both "연결" and "별도" in the text: show the two side by side.
   Otherwise basis is 별도 if "별도" appears, else 연결.
3. Account, first match wins: 현금흐름 (영업활동현금흐름, 영업현금흐름) ->
   operating cash flow; 영업이익; 당기순이익 or 순이익; 매출 or 영업수익;
   자산총계, 총자산, 자산; 부채총계, 총부채, 부채. A bare "이익" with none of
   the above asks back (영업이익 or 당기순이익).
   A keyword counts only when it is not part of a longer account name from
   dart_review/account_vocabulary.json (names seen in the development
   cache): 유동자산, 매출원가, 투자활동현금흐름 and the like are refused as
   unsupported accounts instead of being read as 자산, 매출, 현금흐름. An
   account name of three or more letters that is not supported is refused
   the same way (review B7/C1, 2026-10-08).
4. Years: every "NNNN년". The current year is the latest; the base year is
   the earliest when two differ, else the year before.
5. Period of the current year:
   - balance sheet accounts: a point in time at "N분기말" (month 3N),
     "M월 말" (M = 3, 6, 9, 12), "상반기말" (6), else the year end;
   - flows: year to date for "N분기 누적", "N분기까지", "1~M월", "M월까지",
     "상반기" (6); three months for "N분기" or "A~M월" with A > 1;
     otherwise the whole year.
6. Base period: the same kind in the base year, or the previous quarter
   for "직전 분기" / "전 분기".
The facts are then written by the same renderer as the agent's answers.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from .accounts import ACCOUNTS, normalize_term
from .companies import DEV_COMPANIES
from .render import clarification_answer, structured_answer, unsupported_answer
from .tools import execute_tool

VOCABULARY_FILE = Path(__file__).with_name("account_vocabulary.json")

ACCOUNT_KEYWORDS = [  # first match wins
    ("operating_cash_flow", ("영업활동현금흐름", "영업현금흐름", "현금흐름")),
    ("operating_income", ("영업이익",)),
    ("net_income", ("당기순이익", "순이익")),
    ("revenue", ("매출", "영업수익")),
    ("total_assets", ("자산총계", "총자산", "자산")),
    ("total_liabilities", ("부채총계", "총부채", "부채")),
]
BALANCE_SHEET = ("total_assets", "total_liabilities")


def _unsupported_terms() -> tuple[str, ...]:
    supported = {normalize_term(word) for _, words in ACCOUNT_KEYWORDS for word in words}
    supported |= {normalize_term(name) for account in ACCOUNTS.values() for name in account.names}
    names = json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))["names"]
    return tuple(sorted({name for name in names if name not in supported and len(name) >= 3}))


UNSUPPORTED_TERMS = _unsupported_terms()


@dataclass
class Reading:
    kind: str  # "compare", "side_by_side", "clarify", "unsupported", or "unreadable"
    arguments: dict[str, Any] | None = None
    company: str = ""
    options: tuple[str, ...] = ()
    reason: str = ""


def _account(text: str) -> tuple[str | None, str | None]:
    """(supported account, None), (None, unsupported account name), or (None, None).

    Every keyword and vocabulary name found in ``text`` is a span; a span
    inside a longer one does not count, so 자산 inside 유동자산 is not read
    as 자산총계.
    """
    spans = [(match.start(), match.end(), key) for key, words in ACCOUNT_KEYWORDS for word in words
             for match in re.finditer(re.escape(word), text)]
    spans += [(match.start(), match.end(), None) for term in UNSUPPORTED_TERMS
              for match in re.finditer(re.escape(term), text)]
    outer = [span for span in spans
             if not any(other[0] <= span[0] and span[1] <= other[1] and other[1] - other[0] > span[1] - span[0]
                        for other in spans)]
    refused = sorted(span for span in outer if span[2] is None)
    if refused:
        start, end, _ = refused[0]
        return None, text[start:end]
    found = {span[2] for span in outer}
    return next((key for key, _ in ACCOUNT_KEYWORDS if key in found), None), None


def _month_point(text: str) -> int:
    quarter = re.search(r"([1-4])\s*분기\s*말", text)
    if quarter:
        return int(quarter.group(1)) * 3
    month = re.search(r"(3|6|9|12)\s*월\s*말", text)
    if month:
        return int(month.group(1))
    return 6 if "상반기말" in text or "상반기 말" in text else 12


def _flow_period(text: str) -> tuple[str, int]:
    """(kind, month) for a flow account."""
    cumulative = re.search(r"([1-4])\s*분기\s*(?:누적|까지)", text)
    if cumulative:
        return "year_to_date", int(cumulative.group(1)) * 3
    months = re.search(r"(\d{1,2})\s*[~∼-]\s*(\d{1,2})\s*월", text)
    if months:
        first, last = int(months.group(1)), int(months.group(2))
        return ("year_to_date" if first == 1 else "quarter"), last
    until = re.search(r"(3|6|9|12)\s*월\s*까지", text)
    if until:
        return "year_to_date", int(until.group(1))
    if "상반기" in text:
        return "year_to_date", 6
    quarter = re.search(r"([1-4])\s*분기", text)
    if quarter:
        return "quarter", int(quarter.group(1)) * 3
    return "year_to_date", 12


def read(question: str) -> Reading:
    text = question.replace(" ", " ")
    compact = text.replace(" ", "")
    company = next((name for name in DEV_COMPANIES.values() if name.replace(" ", "") in compact), "")
    if not company:
        return Reading("unreadable", reason="회사 이름을 찾지 못함")
    account, unsupported = _account(compact)
    if unsupported:
        return Reading("unsupported", {"term": unsupported}, company, reason=f"지원하지 않는 계정: {unsupported}")
    if account is None:
        if "이익" in compact:
            return Reading("clarify", company=company, options=("operating_income", "net_income"))
        return Reading("unreadable", company=company, reason="계정을 찾지 못함")
    years = sorted({int(year) for year in re.findall(r"(\d{4})\s*년", text)})
    if not years:
        return Reading("unreadable", company=company, reason="연도를 찾지 못함")
    current_year = years[-1]
    base_year = years[0] if len(years) > 1 else current_year - 1
    if account in BALANCE_SHEET:
        kind, month = "instant", _month_point(text)
    else:
        kind, month = _flow_period(text)
    current = {"kind": kind, "year": current_year, "month": month}
    if "연결" in compact and "별도" in compact:
        return Reading("side_by_side", {"company": company, "account": account, "period": current}, company)
    if re.search(r"(직전|전)\s*분기", text) and kind == "quarter":
        base = {"kind": "quarter", "year": current_year if month > 3 else current_year - 1,
                "month": month - 3 if month > 3 else 12}
    else:
        base = {"kind": kind, "year": base_year, "month": month}
    basis = "별도" if "별도" in compact else "연결"
    return Reading("compare", {"company": company, "basis": basis, "account": account,
                               "current_period": current, "base_period": base}, company)


def baseline_turn(question: str, client: Any, record: dict[str, Any]) -> None:
    """Fill ``record`` the way the agent does, without a model."""
    reading = read(question)
    record["baseline_reading"] = {"kind": reading.kind, "arguments": reading.arguments, "reason": reading.reason}
    if reading.kind == "unreadable":
        record["no_result"] = True
        return
    if reading.kind == "unsupported":
        record["answer"] = unsupported_answer(reading.company, reading.arguments["term"])
        return
    if reading.kind == "clarify":
        record["answer"] = clarification_answer(reading.company, list(reading.options))
        return
    name = "side_by_side" if reading.kind == "side_by_side" else "compare_values"
    result = execute_tool(client, name, reading.arguments)
    record["tool_call_count"] += 1
    record["tool_calls"].append({"raw": None, "name": name, "arguments": reading.arguments, "result": result})
    record["seen"].append(result)
    if "error" in result:
        record["no_result"] = True
        return
    record["answer"] = structured_answer(result)
