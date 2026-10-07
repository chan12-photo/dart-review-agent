"""Answer "how did this account change between two periods" from the cache or the API."""

from __future__ import annotations

from dataclasses import replace

from .accounts import ACCOUNTS, NAME_CONFLICT
from .client import NO_DATA, DartClient, DartResponse, NotCached
from .compare import NOT_COMPARABLE, BasisCheck, Comparison, compare, find_restatements, value_key
from .facts import Fact, fact_from_response
from .periods import (
    ANNUAL, REPORT_END_MONTH, Period, PeriodNotProvided, Source, column_periods, own_source, period_issues,
    plan_comparison, year_to_date,
)


def all_facts(response: DartResponse, account_key: str) -> list[Fact]:
    """The account's value in every column of one report."""
    params = response.params
    sj_div = ACCOUNTS[account_key].statements[0]
    columns = column_periods(int(params["bsns_year"]), params["reprt_code"], sj_div)
    return [fact_from_response(response, account_key, column) for column in columns]


def probe_facts(response: DartResponse, account_key: str) -> list[Fact]:
    """Values of one report usable for checking a shared basis with other reports.

    Besides the reported columns, an income-statement half-year or Q3 report
    implies the year to date of the previous quarter end (year to date minus
    the three months), which the previous report presents directly. These
    derived values are used only for this check, never as answers. Values
    found through a conflicting name are left out.
    """
    facts = [fact for fact in all_facts(response, account_key) if fact.resolved_by != NAME_CONFLICT]
    report_code = response.params["reprt_code"]
    if ACCOUNTS[account_key].statements[0] == "CF" or report_code in (ANNUAL, "11013"):
        return facts
    by_column = {fact.source.column: fact for fact in facts}
    year, month = int(response.params["bsns_year"]), REPORT_END_MONTH[report_code]
    for total, three_months, period_year in (("thstrm_add", "thstrm", year), ("frmtrm_add", "frmtrm_q", year - 1)):
        a, b = by_column.get(total), by_column.get(three_months)
        if a and b and a.available and b.available:
            facts.append(replace(a, period=year_to_date(period_year, month - 3), amount=a.amount - b.amount,
                                 source=Source(year, report_code, f"{total}-{three_months}"), resolved_by="derived",
                                 notes=("같은 보고서의 누적 값에서 3개월 값을 뺀 값 (기준 확인용)",)))
    return facts


def _linked(facts: list[Fact], first: str, second: str) -> bool:
    """Whether two reports (by receipt number) are connected through values presented with equal amounts."""
    parent: dict[str, str] = {}

    def root(node: str) -> str:
        while parent.setdefault(node, node) != node:
            node = parent[node]
        return node

    groups: dict[tuple, list[Fact]] = {}
    for fact in facts:
        if fact.available and fact.rcept_no:
            groups.setdefault(value_key(fact), []).append(fact)
    for group in groups.values():
        for fact in group[1:]:
            if fact.amount == group[0].amount:
                parent[root(fact.rcept_no)] = root(group[0].rcept_no)
    return root(first) == root(second)


def review_change(client: DartClient, corp_code: str, fs_div: str, account_key: str,
                  current: Period, base: Period) -> Comparison:
    """Compare ``account_key`` between ``base`` and the later ``current`` period.

    Both values are read from one report when it presents both (same basis by
    construction); the base value's own report is then read only to note a
    different earlier figure. When two reports are needed, the comparison is
    비교 가능 only if those reports, together with the annual reports in
    between, are linked by values they both present and every such value
    agrees. A disagreement, or a missing link, makes it 확인 필요.
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
        return compare(current_fact, base_fact)  # nothing to compare, so no basis check
    if plan.same_report:
        probes = [base_fact]
        own = own_source(base, sj_div)
        if (own.year, own.report_code) != (plan.current.year, plan.current.report_code):
            try:
                probes.append(fact_from_response(fetch(own.year, own.report_code), account_key, own.column))
            except NotCached:
                pass  # offline without the earlier report: nothing to note
        return compare(current_fact, base_fact, BasisCheck(tuple(find_restatements(probes)), linked=True))
    probes = probe_facts(current_report, account_key) + probe_facts(base_report, account_key)
    used = {(plan.current.year, plan.current.report_code), (plan.base.year, plan.base.report_code)}
    gaps = []
    # annual reports filed between the two link their periods (year ends overlap)
    for year in range(plan.base.year, plan.current.year):
        if (year, ANNUAL) in used:
            continue
        label = f"{year}년 사업보고서"
        try:
            bridge = fetch(year, ANNUAL)
        except NotCached:
            gaps.append(f"{label}가 캐시에 없어 기준이 같은지 확인하지 못했다")
            continue
        if bridge.status == NO_DATA:
            gaps.append(f"{label}가 없어(OpenDART 013) 기준이 같은지 확인하지 못했다")
            continue
        bridge_facts = probe_facts(bridge, account_key)
        if not any(fact.available for fact in bridge_facts):
            gaps.append(f"{label}에서 계정 값을 쓸 수 없어 기준이 같은지 확인하지 못했다")
        probes += bridge_facts
    check = BasisCheck(tuple(find_restatements(probes)),
                       linked=_linked(probes, current_fact.rcept_no, base_fact.rcept_no), gaps=tuple(gaps))
    return compare(current_fact, base_fact, check)
