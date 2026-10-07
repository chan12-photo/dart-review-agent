"""What period each OpenDART amount column covers, per report and statement.

The column names alone are misleading, so the mapping is explicit. Checked on
all 72 cached development reports (docs/DATA_NOTES.ko.md):

- Income statement (IS) and comprehensive income statement (CIS), quarterly
  and half-year reports: ``thstrm`` is the three months of the quarter,
  ``thstrm_add`` is the year to date, ``frmtrm_q`` / ``frmtrm_add`` are the same
  for the prior year.
- Cash flow statement (CF), quarterly and half-year reports: ``thstrm`` is
  already the year to date and ``frmtrm_q`` is the prior year to date. For Q1
  the year to date is the three months; half-year and Q3 reports have no
  column for the quarter alone.
- Balance sheet (BS): point-in-time values. ``frmtrm`` is the prior fiscal
  year end in every report, not the same quarter end of the prior year.
- Annual report: ``thstrm`` / ``frmtrm`` / ``bfefrmtrm`` are this year, the
  prior year, and the year before (year ends for BS).

Assumes a fiscal year that ends in December, which holds for every company in
scope (docs/SCOPE.ko.md section 4).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

ANNUAL = "11011"
REPORT_END_MONTH = {"11013": 3, "11012": 6, "11014": 9, ANNUAL: 12}
REPORT_FOR_END_MONTH = {month: code for code, month in REPORT_END_MONTH.items()}
FLOW_STATEMENTS = ("IS", "CIS", "CF")
SUPPORTED_STATEMENTS = ("BS",) + FLOW_STATEMENTS
STATEMENT_NAMES = {"BS": "재무상태표", "IS": "손익계산서", "CIS": "포괄손익계산서", "CF": "현금흐름표"}


class UnsupportedStatement(ValueError):
    pass


class PeriodNotProvided(ValueError):
    """The requested period is not a column of any report (for example a three-month cash flow)."""


@dataclass(frozen=True, order=True)
class Period:
    """A point in time (``months == 0``) or a flow period of ``months`` months ending at ``end``."""

    end: date
    months: int

    @property
    def is_instant(self) -> bool:
        return self.months == 0

    @property
    def start(self) -> date | None:
        if self.is_instant:
            return None
        index = self.end.year * 12 + self.end.month - self.months
        return date(index // 12, index % 12 + 1, 1)

    @property
    def is_year_to_date(self) -> bool:
        return not self.is_instant and self.start == date(self.end.year, 1, 1)

    def label(self) -> str:
        if self.is_instant:
            return f"{self.end.isoformat()} 시점"
        kind = "누적 " if self.is_year_to_date and self.months > 3 else ""
        return f"{self.start.isoformat()}~{self.end.isoformat()} ({kind}{self.months}개월)"


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def instant(year: int, month: int) -> Period:
    return Period(month_end(year, month), 0)


def quarter(year: int, end_month: int) -> Period:
    return Period(month_end(year, end_month), 3)


def year_to_date(year: int, end_month: int) -> Period:
    return Period(month_end(year, end_month), end_month)


def column_periods(year: int, report_code: str, sj_div: str) -> dict[str, Period]:
    """Columns of a report and the period each one covers, in order of preference."""
    if report_code not in REPORT_END_MONTH:
        raise ValueError(f"unknown report code {report_code}")
    if sj_div not in SUPPORTED_STATEMENTS:
        raise UnsupportedStatement(f"statement {sj_div} is not supported")
    month = REPORT_END_MONTH[report_code]
    if sj_div == "BS":
        columns = {"thstrm": instant(year, month), "frmtrm": instant(year - 1, 12)}
        if report_code == ANNUAL:
            columns["bfefrmtrm"] = instant(year - 2, 12)
        return columns
    if report_code == ANNUAL:
        return {"thstrm": year_to_date(year, 12), "frmtrm": year_to_date(year - 1, 12),
                "bfefrmtrm": year_to_date(year - 2, 12)}
    if sj_div == "CF":
        return {"thstrm": year_to_date(year, month), "frmtrm_q": year_to_date(year - 1, month)}
    return {"thstrm": quarter(year, month), "thstrm_add": year_to_date(year, month),
            "frmtrm_q": quarter(year - 1, month), "frmtrm_add": year_to_date(year - 1, month)}


@dataclass(frozen=True)
class Source:
    """One amount column of one report: which report to fetch and which column to read."""

    year: int
    report_code: str
    column: str

    def period(self, sj_div: str) -> Period:
        return column_periods(self.year, self.report_code, sj_div)[self.column]


def own_source(period: Period, sj_div: str) -> Source:
    """The report whose current-period column covers ``period``."""
    report_code = REPORT_FOR_END_MONTH.get(period.end.month)
    if report_code is None or period.end != month_end(period.end.year, period.end.month):
        raise PeriodNotProvided(f"{period.label()}: reports end only in March, June, September, or December")
    for column, covered in column_periods(period.end.year, report_code, sj_div).items():
        if covered == period and column in ("thstrm", "thstrm_add"):
            return Source(period.end.year, report_code, column)
    if sj_div == "CF" and not period.is_instant and not period.is_year_to_date:
        raise PeriodNotProvided(f"{period.label()}: 현금흐름표는 연초부터의 누적 값만 제공한다 (반기·3분기 보고서에 그 분기만의 값이 없음)")
    if not period.is_instant and period.end.month == 12 and period.months == 3:
        raise PeriodNotProvided(f"{period.label()}: 4분기 3개월 값은 사업보고서에 없다 (연간 값과 3분기 누적 값의 차이로만 계산 가능)")
    raise PeriodNotProvided(f"{period.label()}: {STATEMENT_NAMES[sj_div]}에서 제공하지 않는 기간")


@dataclass(frozen=True)
class Plan:
    current: Source
    base: Source

    @property
    def same_report(self) -> bool:
        return (self.current.year, self.current.report_code) == (self.base.year, self.base.report_code)


def plan_comparison(current: Period, base: Period, sj_div: str) -> Plan:
    """Where to read both values.

    The current value comes from its own report. The base value comes from
    the comparative column of that same report when it has one, because the
    comparative figures are presented on the same basis as the current ones
    (restated if needed). Otherwise the base value comes from its own report.
    """
    current_source = own_source(current, sj_div)
    for column, covered in column_periods(current_source.year, current_source.report_code, sj_div).items():
        if covered == base:
            return Plan(current_source, Source(current_source.year, current_source.report_code, column))
    return Plan(current_source, own_source(base, sj_div))


def period_issues(current: Period, base: Period) -> list[str]:
    """Reasons two periods must not be compared (empty when they can be)."""
    if current.is_instant != base.is_instant:
        return ["시점 값(재무상태표)과 기간 값(손익·현금흐름)은 비교할 수 없다"]
    issues = []
    if current.months != base.months:
        issues.append(f"기간 길이가 다르다 ({current.months}개월과 {base.months}개월)")
    if base.end >= current.end:
        issues.append("기준 기간이 비교 기간보다 앞서야 한다")
    return issues
