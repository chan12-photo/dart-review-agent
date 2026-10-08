"""Comparability traps on the real development cache; skipped when the cache has not been fetched.

Each trap test pins the correct value from the raw response and, where it
helps, the value a naive reading would produce, so the test shows the trap
changes the answer. scripts/check_trap_tests.py re-runs these tests against
naive versions of the rules to confirm each test catches its mistake.
"""

from decimal import Decimal
from pathlib import Path
import unittest

from dart_review.accounts import ACCOUNTS, ID, NAME, resolve_account
from dart_review.cache import ResponseCache
from dart_review.client import DartClient, NotCached
from dart_review.compare import COMPARABLE, NEEDS_REVIEW, NOT_COMPARABLE, compare
from dart_review.companies import DEV_COMPANIES
from dart_review.facts import fact_from_response
from dart_review.periods import REPORT_END_MONTH, Source, instant, own_source, quarter, year_to_date
from dart_review.review import review_change

CACHE = Path(__file__).resolve().parents[1] / "cache"
SAMSUNG, KAKAO, CELLTRION = "00126380", "00258801", "00413046"
YEARS = (2023, 2024, 2025)


def no_key():
    raise AssertionError("cache tests must not need the API key")


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class CacheTestCase(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def fact(self, corp_code, fs_div, account_key, period):
        source = own_source(period, ACCOUNTS[account_key].statements[0])
        return self.fact_at(corp_code, fs_div, account_key, source)

    def fact_at(self, corp_code, fs_div, account_key, source):
        response = self.client.financial_statements(corp_code, source.year, source.report_code, fs_div)
        return fact_from_response(response, account_key, source.column)


class TrapTests(CacheTestCase):
    def test_trap_consolidated_vs_separate(self):
        consolidated = self.fact(SAMSUNG, "CFS", "revenue", year_to_date(2025, 12))
        separate = self.fact(SAMSUNG, "OFS", "revenue", year_to_date(2025, 12))
        self.assertEqual((consolidated.amount, separate.amount), (333_605_938_000_000, 238_043_009_000_000))
        # a valid period order, so only the basis rule can block it (mixing would report +59.58%)
        separate_prior = self.fact(SAMSUNG, "OFS", "revenue", year_to_date(2024, 12))
        result = compare(consolidated, separate_prior)
        self.assertEqual(result.status, NOT_COMPARABLE)
        self.assertEqual(result.reasons, ("연결과 별도 기준은 합치거나 비교하지 않는다 (나란히 보여줄 수만 있다)",))
        self.assertIsNone(result.change)

    def test_trap_three_months_vs_year_to_date(self):
        self.assertEqual(self.fact(SAMSUNG, "CFS", "revenue", quarter(2025, 9)).amount, 86_061_747_000_000)
        self.assertEqual(self.fact(SAMSUNG, "CFS", "revenue", year_to_date(2025, 9)).amount, 239_768_567_000_000)
        result = review_change(self.client, SAMSUNG, "CFS", "revenue", quarter(2025, 9), year_to_date(2024, 9))
        self.assertEqual(result.status, NOT_COMPARABLE)
        result = review_change(self.client, SAMSUNG, "CFS", "revenue", quarter(2025, 9), quarter(2024, 9))
        self.assertEqual((result.status, result.base.amount, result.change_pct),
                         (COMPARABLE, 79_098_731_000_000, Decimal("8.80")))

    def test_trap_quarterly_cash_flow_is_year_to_date(self):
        nine_months = self.fact(SAMSUNG, "CFS", "operating_cash_flow", year_to_date(2025, 9))
        six_months = self.fact(SAMSUNG, "CFS", "operating_cash_flow", year_to_date(2025, 6))
        self.assertEqual((nine_months.source, nine_months.amount), (Source(2025, "11014", "thstrm"), 56_515_496_000_000))
        # read as three months, the column would claim 56.5조 for one quarter; the quarter is only the difference
        self.assertEqual(nine_months.amount - six_months.amount, 22_574_494_000_000)
        result = review_change(self.client, SAMSUNG, "CFS", "operating_cash_flow", quarter(2025, 9), quarter(2024, 9))
        self.assertEqual(result.status, NOT_COMPARABLE)
        self.assertIn("누적 값만", result.reasons[0])
        result = review_change(self.client, SAMSUNG, "CFS", "operating_cash_flow", year_to_date(2025, 9), year_to_date(2024, 9))
        self.assertEqual((result.status, result.base.amount), (COMPARABLE, 50_960_350_000_000))

    def test_trap_balance_sheet_prior_column_is_prior_year_end(self):
        prior_column = self.fact_at(SAMSUNG, "CFS", "total_assets", Source(2025, "11014", "frmtrm"))
        self.assertEqual((prior_column.period, prior_column.amount), (instant(2024, 12), 514_531_948_000_000))
        result = review_change(self.client, SAMSUNG, "CFS", "total_assets", instant(2025, 9), instant(2024, 9))
        self.assertEqual((result.status, result.current.amount, result.base.amount),
                         (COMPARABLE, 523_659_586_000_000, 491_307_317_000_000))
        self.assertEqual(result.base.source, Source(2024, "11014", "thstrm"))

    def test_trap_mistagged_account_id(self):
        rows = self.client.financial_statements(KAKAO, 2023, "11014", "CFS").json()["list"]
        self.assertFalse([row for row in rows if row["account_id"] == "ifrs-full_Revenue"])
        found = resolve_account(rows, "revenue")
        self.assertEqual((found.method, found.row["account_id"], found.row["account_nm"]), (NAME, "ifrs-full_GrossProfit", "영업수익"))
        self.assertEqual(self.fact(KAKAO, "CFS", "revenue", quarter(2023, 9)).amount, 2_160_931_354_165)

    def test_trap_restated_comparative_inside_one_report(self):
        result = review_change(self.client, KAKAO, "CFS", "revenue", quarter(2024, 9), quarter(2023, 9))
        # the 2024 report restated 2023 Q3 revenue; the 2023 report itself said 2,160,931,354,165 (-11.08%)
        self.assertEqual((result.status, result.current.amount, result.base.amount, result.change_pct),
                         (COMPARABLE, 1_921_397_995_104, 2_011_471_714_310, Decimal("-4.48")))
        self.assertTrue(any("2,160,931,354,165" in note for note in result.notes))
        result = review_change(self.client, KAKAO, "CFS", "operating_income", year_to_date(2025, 12), year_to_date(2024, 12))
        self.assertEqual((result.base.amount, result.change_pct), (495_277_757_353, Decimal("47.80")))

    def test_trap_restatement_between_two_reports(self):
        result = review_change(self.client, CELLTRION, "CFS", "total_assets", instant(2025, 9), instant(2024, 9))
        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertIn("2023-12-31", result.reasons[0])
        self.assertIsNotNone(result.change)

    def test_reports_that_cannot_be_linked_need_review(self):
        # Codex review R1: without the 2024 annual report nothing links the two Q3 reports
        client = self.client

        class WithoutBridge:
            def financial_statements(self, corp_code, year, report_code, fs_div):
                if (year, report_code) == (2024, "11011"):
                    raise NotCached("bridge withheld for the test")
                return client.financial_statements(corp_code, year, report_code, fs_div)

        result = review_change(WithoutBridge(), SAMSUNG, "CFS", "total_assets", instant(2025, 9), instant(2024, 9))
        self.assertEqual((result.status, result.change), (NEEDS_REVIEW, 32_352_269_000_000))
        self.assertIn("2024년 사업보고서", result.reasons[0])

    def test_quarters_of_one_year_link_through_the_year_to_date(self):
        result = review_change(self.client, KAKAO, "CFS", "revenue", quarter(2023, 9), quarter(2023, 6))
        self.assertEqual((result.status, result.change_pct), (COMPARABLE, Decimal("5.80")))
        self.assertTrue(any("모두 일치" in note for note in result.notes))

    def test_sign_changes(self):
        result = review_change(self.client, KAKAO, "CFS", "net_income", year_to_date(2024, 12), year_to_date(2023, 12))
        self.assertEqual((result.direction, result.change_pct), ("적자 축소", None))
        result = review_change(self.client, KAKAO, "CFS", "net_income", year_to_date(2025, 12), year_to_date(2024, 12))
        self.assertEqual((result.direction, result.change_pct), ("흑자 전환", None))


class WholeCacheTests(CacheTestCase):
    """The period model and account resolution hold on every cached development report."""

    def responses(self):
        for corp_code in DEV_COMPANIES:
            for fs_div in ("CFS", "OFS"):
                for year in YEARS:
                    for report_code in REPORT_END_MONTH:
                        yield corp_code, fs_div, year, report_code, self.client.financial_statements(corp_code, year, report_code, fs_div)

    def test_every_target_account_resolves_once(self):
        by_name = []
        for corp_code, fs_div, year, report_code, response in self.responses():
            rows = response.json()["list"]
            for key in ACCOUNTS:
                found = resolve_account(rows, key)
                self.assertIn(found.method, (ID, NAME), (corp_code, fs_div, year, report_code, key))
                if found.method == NAME:
                    by_name.append((corp_code, year, report_code, key))
        # only Kakao's 2023 quarterly revenue (consolidated and separate) needs the name
        self.assertEqual(sorted(set(by_name)), [(KAKAO, 2023, code, "revenue") for code in ("11012", "11013", "11014")])
        self.assertEqual(len(by_name), 6)

    def test_three_month_values_add_up_to_year_to_date(self):
        checked = 0
        for corp_code in DEV_COMPANIES:
            for fs_div in ("CFS", "OFS"):
                for year in YEARS:
                    for key in ("revenue", "operating_income", "net_income"):
                        get = lambda period: self.fact(corp_code, fs_div, key, period).amount
                        self.assertEqual(get(year_to_date(year, 6)), get(year_to_date(year, 3)) + get(quarter(year, 6)))
                        self.assertEqual(get(year_to_date(year, 9)), get(year_to_date(year, 6)) + get(quarter(year, 9)))
                        checked += 2
        self.assertEqual(checked, 108)

    def test_quarterly_balance_sheets_compare_with_the_prior_year_end(self):
        checked = 0
        for corp_code in DEV_COMPANIES:
            for fs_div in ("CFS", "OFS"):
                for year in (2024, 2025):
                    for key in ("total_assets", "total_liabilities"):
                        year_end = self.fact(corp_code, fs_div, key, instant(year - 1, 12)).amount
                        for report_code in ("11013", "11012", "11014"):
                            prior = self.fact_at(corp_code, fs_div, key, Source(year, report_code, "frmtrm"))
                            self.assertEqual((prior.period, prior.amount), (instant(year - 1, 12), year_end))
                            checked += 1
        self.assertEqual(checked, 72)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class VocabularyTests(unittest.TestCase):
    def test_the_committed_account_vocabulary_matches_the_cache(self):
        import subprocess
        import sys
        script = Path(__file__).resolve().parents[1] / "scripts" / "build_account_vocabulary.py"
        result = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

