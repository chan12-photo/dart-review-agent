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
7. (3-1 preparation, EVAL_DESIGN 12) Company by the longest name
   (dart_review/company_names.py): another company whose name contains a
   supported one, or several companies, is out of scope; a group name alone
   is asked back. Two or more different accounts are out of scope. Without
   a four-digit year, 올해/작년/재작년 are read from the reference date, and
   with no year at all the latest annual report year is used. With no
   comparison word and at most one year the question is a value lookup.
The facts are then written by the same renderer as the agent's answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from .accounts import ACCOUNTS, normalize_term
from .company_names import resolve_company
from .companies import supported_companies
from .render import clarification_answer, company_clarification_answer, structured_answer, unsupported_answer
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
    kind: str  # "compare", "side_by_side", "lookup", "clarify", "clarify_company", "unsupported", or "unreadable"
    arguments: dict[str, Any] | None = None
    company: str = ""
    options: tuple[str, ...] = ()
    reason: str = ""


def _account(text: str) -> tuple[str | None, str | None, tuple[str, ...]]:
    """(account, None, ()), (None, unsupported account name, ()), (None, None, several accounts), or (None, None, ()).

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
        return None, text[start:end], ()
    found = [key for key, _ in ACCOUNT_KEYWORDS if key in {span[2] for span in outer}]
    if len(found) > 1:
        return None, None, tuple(found)
    return (found[0] if found else None), None, ()


def latest_annual_year(reference_date: date) -> int:
    """The latest year whose annual report is due by ``reference_date`` (due by the end of March)."""
    return reference_date.year - 1 if (reference_date.month, reference_date.day) >= (4, 1) else reference_date.year - 2


def _years(text: str, reference_date: date) -> list[int]:
    explicit = sorted({int(year) for year in re.findall(r"(\d{4})\s*년", text)})
    if explicit:
        return explicit
    relative = set()
    if re.search(r"올해|금년", text):
        relative.add(reference_date.year)
    if re.search(r"(?<!재)작년|지난\s*해", text):
        relative.add(reference_date.year - 1)
    if "재작년" in text:
        relative.add(reference_date.year - 2)
    return sorted(relative)


def default_year_note(question: str, reference_date: date) -> str | None:
    """The note shown when the question names no year (EVAL_DESIGN 12.2)."""
    if _years(question, reference_date):
        return None
    return f"연도를 말하지 않아 가장 최근 사업보고서 연도({latest_annual_year(reference_date)}년)로 봤습니다."


_FLOW_NAMES = re.compile(r"(?:(\d{4})\s*년\s*)?(?:([1-4])\s*분기(?!\s*(?:말|누적|까지))|(\d{1,2})\s*[~∼-]\s*(\d{1,2})\s*월)")
_POINT_NAMES = re.compile(r"(?:(\d{4})\s*년\s*)?(?:([1-4])\s*분기\s*말|(3|6|9|12)\s*월\s*말)")


def _named_periods(text: str, balance_sheet: bool, first_year: int) -> list[dict[str, Any]]:
    """Periods named one by one, in order ("2025년 1분기와 2분기", "7~9월 … 4~6월"); Codex 3-1 first review 7.

    A period without its own four-digit year takes the year named before it, or ``first_year``.
    """
    periods, year = [], first_year
    for match in (_POINT_NAMES if balance_sheet else _FLOW_NAMES).finditer(text):
        year = int(match.group(1)) if match.group(1) else year
        if balance_sheet:
            period = {"kind": "instant", "year": year, "month": int(match.group(2)) * 3 if match.group(2) else int(match.group(3))}
        elif match.group(2):
            period = {"kind": "quarter", "year": year, "month": int(match.group(2)) * 3}
        else:
            first, last = int(match.group(3)), int(match.group(4))
            period = {"kind": "year_to_date" if first == 1 else "quarter", "year": year, "month": last}
        if period not in periods:
            periods.append(period)
    return periods


_COMPARISON = re.compile(r"보다|대비|비교|전년|전기|직전|증감|증가|감소|늘었|늘어|늘린|줄었|줄어|변화|성장|차이")


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


def read(question: str, reference_date: date | None = None) -> Reading:
    reference_date = reference_date or date.today()
    text = question.replace(" ", " ")
    compact = text.replace(" ", "")
    match = resolve_company(text)  # with its spaces: a name must stand as a word (company_names._bounded)
    if match.kind == "none":
        return Reading("unreadable", reason="회사 이름을 찾지 못함")
    if match.kind in ("unsupported", "sealed", "several"):
        scope = "companies" if match.kind == "several" else "company"
        return Reading("unsupported", {"term": match.name, "scope": scope}, match.name,
                       reason=f"{'회사 여러 개' if match.kind == 'several' else '지원하지 않는 회사'}: {match.name}")
    if match.kind == "group":
        return Reading("clarify_company", company=match.name, options=match.candidates)
    company = supported_companies()[match.corp_code]
    account, unsupported, several = _account(compact)
    if unsupported:
        return Reading("unsupported", {"term": unsupported, "scope": "account"}, company,
                       reason=f"지원하지 않는 계정: {unsupported}")
    if several:
        labels = ", ".join(ACCOUNTS[key].label for key in several)
        return Reading("unsupported", {"term": labels, "scope": "accounts"}, company, reason=f"계정 여러 개: {labels}")
    if account is None:
        if "이익" in compact:
            return Reading("clarify", company=company, options=("operating_income", "net_income"))
        return Reading("unreadable", company=company, reason="계정을 찾지 못함")
    years = _years(text, reference_date) or [latest_annual_year(reference_date)]
    current_year = years[-1]
    base_year = years[0] if len(years) > 1 else current_year - 1
    if account in BALANCE_SHEET:
        kind, month = "instant", _month_point(text)
    else:
        kind, month = _flow_period(text)
    current = {"kind": kind, "year": current_year, "month": month}
    if "연결" in compact and "별도" in compact:
        return Reading("side_by_side", {"company": company, "account": account, "period": current}, company)
    basis = "별도" if "별도" in compact else "연결"
    named = _named_periods(text, account in BALANCE_SHEET, years[0])
    if len(named) == 2:  # two periods named one by one are compared, later against earlier
        base, current = sorted(named, key=lambda period: (period["year"], period["month"]))
        if base != current:
            return Reading("compare", {"company": company, "basis": basis, "account": account,
                                       "current_period": current, "base_period": base}, company)
    if not _COMPARISON.search(compact) and len(years) == 1:
        return Reading("lookup", {"company": company, "basis": basis, "account": account, "period": current}, company)
    if re.search(r"(직전|전)\s*분기", text) and kind == "quarter":
        base = {"kind": "quarter", "year": current_year if month > 3 else current_year - 1,
                "month": month - 3 if month > 3 else 12}
    else:
        base = {"kind": kind, "year": base_year, "month": month}
    return Reading("compare", {"company": company, "basis": basis, "account": account,
                               "current_period": current, "base_period": base}, company)


def baseline_turn(question: str, client: Any, record: dict[str, Any], reference_date: date | None = None) -> None:
    """Fill ``record`` the way the agent does, without a model."""
    reference_date = reference_date or date.today()
    reading = read(question, reference_date)
    record["baseline_reading"] = {"kind": reading.kind, "arguments": reading.arguments, "reason": reading.reason}
    if reading.kind == "unreadable":
        record["no_result"] = True
        return
    if reading.kind == "unsupported":
        record["answer"] = unsupported_answer(reading.company, reading.arguments["term"], reading.arguments["scope"])
        return
    if reading.kind == "clarify_company":
        record["answer"] = company_clarification_answer(reading.company, list(reading.options))
        return
    if reading.kind == "clarify":
        record["answer"] = clarification_answer(reading.company, list(reading.options))
        return
    name = {"side_by_side": "side_by_side", "lookup": "lookup_value"}.get(reading.kind, "compare_values")
    result = execute_tool(client, name, reading.arguments)
    record["tool_call_count"] += 1
    record["tool_calls"].append({"raw": None, "name": name, "arguments": reading.arguments, "result": result})
    record["seen"].append(result)
    if "error" in result:
        record["no_result"] = True
        return
    answer = structured_answer(result)
    note = default_year_note(question, reference_date)
    if note:
        answer["answer"] = note + "\n" + answer["answer"]
    record["answer"] = answer
