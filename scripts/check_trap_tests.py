"""Show that each trap test catches its mistake.

For every trap, swap one rule for the naive version a developer would plausibly
write, run the cache-based tests, and require the trap's own test to fail.
Run without mutations first to require that every test passes. Needs the
development cache (scripts/fetch_dev_cache.py); makes no network requests.

    python scripts/check_trap_tests.py
"""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import sys
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from dart_review import accounts, compare, periods  # noqa: E402
from dart_review.periods import (  # noqa: E402
    ANNUAL, REPORT_END_MONTH, Plan, instant, own_source, quarter, year_to_date,
)
import test_rules_on_cache  # noqa: E402

original_column_periods = periods.column_periods


def naive_columns(override):
    def column_periods(year, report_code, sj_div):
        columns = original_column_periods(year, report_code, sj_div)
        return override(year, report_code, sj_div, columns) or columns
    return column_periods


def thstrm_is_year_to_date(year, report_code, sj_div, columns):
    # "당기" read as the cumulative amount in the income statement too
    if sj_div in ("IS", "CIS") and report_code != ANNUAL:
        month = REPORT_END_MONTH[report_code]
        return {**columns, "thstrm": year_to_date(year, month)}


def cash_flow_as_three_months(year, report_code, sj_div, columns):
    # cash flow columns read like the income statement's three-month columns
    if sj_div == "CF" and report_code != ANNUAL:
        month = REPORT_END_MONTH[report_code]
        return {"thstrm": quarter(year, month), "frmtrm_q": quarter(year - 1, month)}


def balance_sheet_prior_is_same_quarter(year, report_code, sj_div, columns):
    # "전기" read as the same quarter end of the prior year
    if sj_div == "BS" and report_code != ANNUAL:
        return {**columns, "frmtrm": instant(year - 1, REPORT_END_MONTH[report_code])}


original_structural_issues = compare.structural_issues
original_resolve_account = accounts.resolve_account


def ignore_fs_div(current, base):
    return original_structural_issues(current, replace(base, fs_div=current.fs_div))


def id_only(rows, key):
    found = original_resolve_account(rows, key)
    return found if found.method != accounts.NAME else accounts.Resolution(found.account, accounts.NOT_FOUND, None)


def base_from_its_own_report(current, base, sj_div):
    return Plan(own_source(current, sj_div), own_source(base, sj_div))


MUTATIONS = [
    ("연결·별도 구분 무시", "structural_issues", ignore_fs_div, "test_trap_consolidated_vs_separate"),
    ("손익 당기를 누적으로 읽음", "column_periods", naive_columns(thstrm_is_year_to_date), "test_trap_three_months_vs_year_to_date"),
    ("현금흐름 당기를 3개월로 읽음", "column_periods", naive_columns(cash_flow_as_three_months), "test_trap_quarterly_cash_flow_is_year_to_date"),
    ("재무상태표 전기를 전년 같은 분기말로 읽음", "column_periods", naive_columns(balance_sheet_prior_is_same_quarter),
     "test_trap_balance_sheet_prior_column_is_prior_year_end"),
    ("표준계정ID만 사용", "resolve_account", id_only, "test_trap_mistagged_account_id"),
    ("전기 값을 그 기간의 원래 보고서에서 읽음", "plan_comparison", base_from_its_own_report,
     "test_trap_restated_comparative_inside_one_report"),
    ("재작성 확인 생략", "find_restatements", lambda facts: [], "test_trap_restatement_between_two_reports"),
]


def patch_everywhere(stack: ExitStack, name: str, replacement) -> None:
    """Replace ``name`` in every loaded module that imported the original object."""
    original = getattr(sys.modules["dart_review." + _home(name)], name)
    for module in list(sys.modules.values()):
        if getattr(module, name, None) is original:
            stack.enter_context(mock.patch.object(module, name, replacement))


def _home(name: str) -> str:
    for module in ("periods", "accounts", "compare", "facts", "review"):
        if name in vars(sys.modules["dart_review." + module]):
            return module
    raise KeyError(name)


def run_tests() -> tuple[int, set[str]]:
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_rules_on_cache)
    result = unittest.TestResult()
    suite.run(result)
    failed = {test.id().rsplit(".", 1)[-1] for test, _ in result.failures + result.errors}
    return result.testsRun, failed


def main() -> int:
    if not test_rules_on_cache.CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    total, failed = run_tests()
    print(f"원래 규칙: {total}개 중 실패 {len(failed)}개 {sorted(failed) or ''}")
    ok = not failed
    for label, name, replacement, expected in MUTATIONS:
        with ExitStack() as stack:
            patch_everywhere(stack, name, replacement)
            _, failed = run_tests()
        caught = expected in failed
        ok &= caught
        print(f"{'잡힘' if caught else '놓침'} | {label} | 실패한 테스트 {len(failed)}개: {', '.join(sorted(failed))}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
