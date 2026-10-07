"""Answer "how did this account change between two periods" from the cache or the API."""

from __future__ import annotations

from dataclasses import replace

from .accounts import ACCOUNTS
from .client import DartClient, DartResponse, NotCached
from .compare import NOT_COMPARABLE, Comparison, compare, find_restatements
from .facts import Fact, fact_from_response
from .periods import ANNUAL, Period, PeriodNotProvided, column_periods, own_source, period_issues, plan_comparison


def all_facts(response: DartResponse, account_key: str) -> list[Fact]:
    """The account's value in every column of one report."""
    params = response.params
    sj_div = ACCOUNTS[account_key].statements[0]
    columns = column_periods(int(params["bsns_year"]), params["reprt_code"], sj_div)
    return [fact_from_response(response, account_key, column) for column in columns]


def review_change(client: DartClient, corp_code: str, fs_div: str, account_key: str,
                  current: Period, base: Period) -> Comparison:
    """Compare ``account_key`` between ``base`` and the later ``current`` period.

    Both values are read from one report when it presents both; the base
    value's own report is then read only to note a restatement. When two
    reports are needed, every overlapping period they and the annual reports
    in between present is checked for restatements, and a restatement between
    them makes the result 확인 필요.
    """
    sj_div = ACCOUNTS[account_key].statements[0]
    issues = period_issues(current, base)
    if issues:
        return Comparison(NOT_COMPARABLE, tuple(issues), (), None, None)
    try:
        plan = plan_comparison(current, base, sj_div)
    except PeriodNotProvided as exc:
        return Comparison(NOT_COMPARABLE, (str(exc),), (), None, None)

    def fetch(year: int, report_code: str) -> DartResponse:
        return client.financial_statements(corp_code, year, report_code, fs_div)

    current_report = fetch(plan.current.year, plan.current.report_code)
    base_report = current_report if plan.same_report else fetch(plan.base.year, plan.base.report_code)
    current_fact = fact_from_response(current_report, account_key, plan.current.column)
    base_fact = fact_from_response(base_report, account_key, plan.base.column)
    if not (current_fact.available and base_fact.available):
        return compare(current_fact, base_fact)  # nothing to compare, so no restatement probe
    if plan.same_report:
        probes = [base_fact]
        own = own_source(base, sj_div)
        if (own.year, own.report_code) != (plan.current.year, plan.current.report_code):
            try:
                probes.append(fact_from_response(fetch(own.year, own.report_code), account_key, own.column))
            except NotCached:
                pass  # offline without the original report: nothing to note
        return compare(current_fact, base_fact, find_restatements(probes))
    probes = all_facts(current_report, account_key) + all_facts(base_report, account_key)
    used = {(plan.current.year, plan.current.report_code), (plan.base.year, plan.base.report_code)}
    unchecked = []
    # annual reports filed between the two link their periods (year ends overlap)
    for bridge in [(year, ANNUAL) for year in range(plan.base.year, plan.current.year)]:
        if bridge in used:
            continue
        try:
            probes += all_facts(fetch(*bridge), account_key)
        except NotCached:
            unchecked.append(f"{bridge[0]}년 사업보고서가 캐시에 없어 재작성 여부를 끝까지 확인하지 못했다")
    result = compare(current_fact, base_fact, find_restatements(probes))
    return replace(result, notes=result.notes + tuple(unchecked)) if unchecked else result
