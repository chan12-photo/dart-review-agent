"""Unit tests for the period model, account resolution, and comparability rules (synthetic rows)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from dart_review.accounts import AMBIGUOUS, ID, NAME, NAME_CONFLICT, NOT_FOUND, resolve_account
from dart_review.cache import ResponseCache
from dart_review.client import DartClient, DartResponse
from dart_review.compare import (
    COMPARABLE, NEEDS_REVIEW, NO_DATA, NOT_COMPARABLE, BasisCheck, compare, find_restatements,
)
from dart_review.facts import UnexpectedAmount, fact_from_response, parse_amount
from dart_review.review import review_change
from dart_review.periods import (
    Period, PeriodNotProvided, Source, UnsupportedStatement, column_periods, instant, own_source, period_issues,
    plan_comparison, quarter, year_to_date,
)

CORP = "00000001"


def row(sj_div, account_id, account_nm, detail="-", year=2025, report="11014", **amounts):
    filed = {"11013": f"{year}0515", "11012": f"{year}0814", "11014": f"{year}1114", "11011": f"{year + 1}0317"}[report]
    data = {"rcept_no": filed + "000001", "reprt_code": report,
            "bsns_year": str(year), "corp_code": CORP, "sj_div": sj_div, "account_id": account_id,
            "account_nm": account_nm, "account_detail": detail, "currency": "KRW"}
    data.update({f"{column}_amount": value for column, value in amounts.items()})
    return data


def response(rows, year=2025, report="11014", fs_div="CFS", status="000"):
    body = json.dumps({"status": status, "message": "", "list": rows}, ensure_ascii=False).encode("utf-8")
    params = {"corp_code": CORP, "bsns_year": str(year), "reprt_code": report, "fs_div": fs_div}
    return DartResponse("fnlttSinglAcntAll.json", params, status, "", body, "2026-10-07T00:00:00+00:00", "0" * 64, True)


class PeriodTests(unittest.TestCase):
    def test_period_dates_and_labels(self):
        self.assertEqual(quarter(2025, 9).start, date(2025, 7, 1))
        self.assertEqual(year_to_date(2025, 9).start, date(2025, 1, 1))
        self.assertEqual(quarter(2025, 3), year_to_date(2025, 3))
        self.assertEqual(instant(2024, 6).label(), "2024-06-30 시점")
        self.assertEqual(year_to_date(2025, 9).label(), "2025-01-01~2025-09-30 (누적 9개월)")
        self.assertEqual(quarter(2025, 9).label(), "2025-07-01~2025-09-30 (3개월)")

    def test_quarterly_income_statement_columns(self):
        for sj_div in ("IS", "CIS"):
            self.assertEqual(column_periods(2025, "11014", sj_div), {
                "thstrm": quarter(2025, 9), "thstrm_add": year_to_date(2025, 9),
                "frmtrm_q": quarter(2024, 9), "frmtrm_add": year_to_date(2024, 9)})

    def test_quarterly_cash_flow_columns_are_year_to_date(self):
        self.assertEqual(column_periods(2025, "11014", "CF"),
                         {"thstrm": year_to_date(2025, 9), "frmtrm_q": year_to_date(2024, 9)})

    def test_balance_sheet_prior_column_is_prior_year_end(self):
        for report in ("11013", "11012", "11014"):
            self.assertEqual(column_periods(2025, report, "BS")["frmtrm"], instant(2024, 12))
        self.assertEqual(column_periods(2025, "11011", "BS"),
                         {"thstrm": instant(2025, 12), "frmtrm": instant(2024, 12), "bfefrmtrm": instant(2023, 12)})

    def test_annual_flow_columns(self):
        for sj_div in ("IS", "CIS", "CF"):
            self.assertEqual(column_periods(2025, "11011", sj_div), {
                "thstrm": year_to_date(2025, 12), "frmtrm": year_to_date(2024, 12), "bfefrmtrm": year_to_date(2023, 12)})

    def test_unsupported_statement(self):
        with self.assertRaises(UnsupportedStatement):
            column_periods(2025, "11011", "SCE")

    def test_own_source(self):
        self.assertEqual(own_source(quarter(2025, 9), "IS"), Source(2025, "11014", "thstrm"))
        self.assertEqual(own_source(year_to_date(2025, 9), "IS"), Source(2025, "11014", "thstrm_add"))
        self.assertEqual(own_source(year_to_date(2025, 9), "CF"), Source(2025, "11014", "thstrm"))
        self.assertEqual(own_source(quarter(2025, 3), "IS"), Source(2025, "11013", "thstrm"))
        self.assertEqual(own_source(instant(2024, 12), "BS"), Source(2024, "11011", "thstrm"))

    def test_periods_no_report_provides(self):
        cases = [(quarter(2025, 9), "CF", "누적 값만"), (quarter(2025, 12), "IS", "4분기"),
                 (Period(date(2025, 8, 31), 0), "BS", "March, June"), (Period(date(2025, 9, 30), 6), "IS", "제공하지 않는")]
        for period, sj_div, text in cases:
            with self.subTest(period=period, sj_div=sj_div):
                with self.assertRaises(PeriodNotProvided) as caught:
                    own_source(period, sj_div)
                self.assertIn(text, str(caught.exception))

    def test_plan_prefers_the_comparative_column_of_the_current_report(self):
        plan = plan_comparison(quarter(2025, 9), quarter(2024, 9), "IS")
        self.assertTrue(plan.same_report)
        self.assertEqual(plan.base, Source(2025, "11014", "frmtrm_q"))
        plan = plan_comparison(year_to_date(2025, 12), year_to_date(2023, 12), "IS")
        self.assertEqual(plan.base, Source(2025, "11011", "bfefrmtrm"))

    def test_plan_reads_another_report_when_needed(self):
        plan = plan_comparison(instant(2025, 9), instant(2024, 9), "BS")
        self.assertFalse(plan.same_report)
        self.assertEqual((plan.current, plan.base), (Source(2025, "11014", "thstrm"), Source(2024, "11014", "thstrm")))

    def test_period_issues(self):
        self.assertEqual(period_issues(quarter(2025, 9), quarter(2024, 9)), [])
        self.assertIn("시점 값", period_issues(instant(2025, 9), quarter(2024, 9))[0])
        self.assertIn("3개월과 9개월", period_issues(quarter(2025, 9), year_to_date(2024, 9))[0])
        self.assertIn("앞서야", period_issues(quarter(2024, 9), quarter(2025, 9))[0])


class AmountTests(unittest.TestCase):
    def test_parse_amount(self):
        self.assertEqual(parse_amount("123"), 123)
        self.assertEqual(parse_amount("-1,234"), -1234)
        for empty in ("", "-", None, "  "):
            self.assertIsNone(parse_amount(empty))
        for bad in ("1.5", "12억", "--3"):
            with self.assertRaises(UnexpectedAmount):
                parse_amount(bad)


class ResolutionTests(unittest.TestCase):
    def test_id_in_income_statement_wins_over_comprehensive(self):
        rows = [row("CIS", "ifrs-full_ProfitLoss", "당기순이익", thstrm="2"), row("IS", "ifrs-full_ProfitLoss", "당기순이익", thstrm="1")]
        found = resolve_account(rows, "net_income")
        self.assertEqual((found.method, found.row["sj_div"]), (ID, "IS"))

    def test_comprehensive_statement_when_there_is_no_income_statement(self):
        found = resolve_account([row("CIS", "ifrs-full_Revenue", "영업수익", thstrm="5")], "revenue")
        self.assertEqual((found.method, found.row["sj_div"]), (ID, "CIS"))

    def test_other_statements_are_ignored(self):
        rows = [row("SCE", "ifrs-full_ProfitLoss", "당기순이익", detail="이익잉여금 [member]", thstrm="9"),
                row("CF", "ifrs-full_ProfitLoss", "당기순이익", thstrm="8")]
        self.assertEqual(resolve_account(rows, "net_income").method, NOT_FOUND)

    def test_breakdown_rows_in_the_same_statement_are_ignored(self):
        total = row("IS", "ifrs-full_Revenue", "매출액", thstrm="10")
        breakdown = row("IS", "ifrs-full_Revenue", "매출액", detail="반도체 부문 [member]", thstrm="99")
        found = resolve_account([breakdown, total], "revenue")
        self.assertEqual((found.method, found.row["thstrm_amount"]), (ID, "10"))
        self.assertEqual(resolve_account([breakdown], "revenue").method, NOT_FOUND)

    def test_name_with_a_conflicting_standard_id_needs_review(self):
        found = resolve_account([row("IS", "ifrs-full_ProfitLossAttributableToOwnersOfParent", "당기순이익", thstrm="5")], "net_income")
        self.assertEqual(found.method, NAME_CONFLICT)
        self.assertIn("ifrs-full_ProfitLossAttributableToOwnersOfParent", found.notes[0])
        found = resolve_account([row("CIS", "ifrs-full_GrossProfit", "영업수익", thstrm="5")], "revenue")
        self.assertEqual(found.method, NAME_CONFLICT)

    def test_verified_mistag_is_accepted(self):
        kakao_row = {**row("CIS", "ifrs-full_GrossProfit", "영업수익", thstrm="5"), "corp_code": "00258801"}
        found = resolve_account([kakao_row], "revenue")
        self.assertEqual(found.method, NAME)
        self.assertIn("확인된 오표기", found.notes[0])

    def test_name_fallback_ignores_whitespace(self):
        found = resolve_account([row("CF", "-표준계정코드 미사용-", "영업활동으로 인한 현금흐름", thstrm="5")], "operating_cash_flow")
        self.assertEqual(found.method, NAME)
        self.assertNotIn("표기됨", found.notes[0])

    def test_two_candidates_are_ambiguous(self):
        rows = [row("BS", "ifrs-full_Assets", "자산총계", thstrm="1"), row("BS", "ifrs-full_Assets", "자산총계", thstrm="2")]
        found = resolve_account(rows, "total_assets")
        self.assertEqual(found.method, AMBIGUOUS)
        self.assertIsNone(found.row)
        self.assertEqual(len(found.candidates), 2)


class FactTests(unittest.TestCase):
    def test_period_comes_from_the_column_map(self):
        rows = [row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", thstrm="90", frmtrm_q="80")]
        fact = fact_from_response(response(rows), "operating_cash_flow", "thstrm")
        self.assertEqual((fact.amount, fact.period), (90, year_to_date(2025, 9)))

    def test_column_that_the_statement_does_not_have(self):
        rows = [row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", thstrm="90")]
        with self.assertRaises(ValueError):
            fact_from_response(response(rows), "operating_cash_flow", "thstrm_add")

    def test_no_data_and_empty_column(self):
        fact = fact_from_response(response([], status="013"), "revenue", "thstrm")
        self.assertFalse(fact.available)
        self.assertIn("013", fact.notes[0])
        fact = fact_from_response(response([row("IS", "ifrs-full_Revenue", "매출액", thstrm="")]), "revenue", "thstrm")
        self.assertFalse(fact.available)
        self.assertIn("비어 있음", fact.notes[-1])

    def test_rows_from_another_report_are_rejected(self):
        with self.assertRaises(ValueError):
            fact_from_response(response([row("IS", "ifrs-full_Revenue", "매출액", year=2024, thstrm="1")]), "revenue", "thstrm")


def fact(amount, period=None, fs_div="CFS", account="revenue", rcept="20251114000001", currency="KRW"):
    rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm=str(amount)),
            row("IS", "dart_OperatingIncomeLoss", "영업이익", thstrm=str(amount)),
            row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름", thstrm=str(amount))]
    base = fact_from_response(response(rows, fs_div=fs_div), account, "thstrm")
    return replace(base, period=period or base.period, rcept_no=rcept, currency=currency)


class CompareTests(unittest.TestCase):
    def test_comparable_change(self):
        result = compare(fact(110), fact(100, quarter(2024, 9)))
        self.assertEqual((result.status, result.change, result.change_pct, result.direction),
                         (COMPARABLE, 10, Decimal("10.00"), "증가"))

    def test_consolidated_and_separate_are_not_compared(self):
        result = compare(fact(110), fact(100, quarter(2024, 9), fs_div="OFS"))
        self.assertEqual(result.status, NOT_COMPARABLE)
        self.assertIsNone(result.change)
        self.assertIn("연결과 별도", result.reasons[0])

    def test_period_length_and_currency(self):
        self.assertEqual(compare(fact(110), fact(100, year_to_date(2024, 9))).status, NOT_COMPARABLE)
        result = compare(fact(110), fact(100, quarter(2024, 9), currency="USD"))
        self.assertEqual(result.status, NOT_COMPARABLE)
        self.assertIn("통화", result.reasons[0])

    def test_zero_and_negative_bases(self):
        result = compare(fact(50), fact(0, quarter(2024, 9)))
        self.assertEqual((result.status, result.change, result.change_pct), (COMPARABLE, 50, None))
        self.assertIn("0 이하", result.notes[-1])
        profit = dict(account="operating_income")
        self.assertEqual(compare(fact(5, **profit), fact(-3, quarter(2024, 9), **profit)).direction, "흑자 전환")
        self.assertEqual(compare(fact(-5, **profit), fact(3, quarter(2024, 9), **profit)).direction, "적자 전환")
        self.assertEqual(compare(fact(-2, **profit), fact(-3, quarter(2024, 9), **profit)).direction, "적자 축소")
        self.assertEqual(compare(fact(-5), fact(3, quarter(2024, 9))).direction, "감소")

    def test_missing_value_is_no_data(self):
        self.assertEqual(compare(None, fact(1)).status, NO_DATA)
        missing = fact_from_response(response([], status="013"), "revenue", "thstrm")
        result = compare(missing, fact(100, quarter(2024, 9)))
        self.assertEqual(result.status, NO_DATA)
        self.assertIn("013", result.reasons[0])

    def test_ambiguous_account_needs_review(self):
        rows = [row("IS", "ifrs-full_Revenue", "매출액", thstrm="1"), row("IS", "ifrs-full_Revenue", "매출액", thstrm="2")]
        ambiguous = fact_from_response(response(rows), "revenue", "thstrm")
        result = compare(ambiguous, fact(100, quarter(2024, 9)))
        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertIsNone(result.change)

    def test_rate_rounds_halves_away_from_zero(self):
        self.assertEqual(compare(fact(100_005), fact(100_000, quarter(2024, 9))).change_pct, Decimal("0.01"))
        self.assertEqual(compare(fact(99_995), fact(100_000, quarter(2024, 9))).change_pct, Decimal("-0.01"))
        self.assertEqual(compare(fact(1_000_049), fact(1_000_000, quarter(2024, 9))).change_pct, Decimal("0.00"))
        self.assertEqual(compare(fact(0), fact(100, quarter(2024, 9))).change_pct, Decimal("-100.00"))

    def test_cash_flow_sign_change_is_not_called_profit_or_loss(self):
        cash = dict(account="operating_cash_flow")
        result = compare(fact(5, year_to_date(2025, 9), **cash), fact(-3, year_to_date(2024, 9), **cash))
        self.assertEqual((result.status, result.change_pct, result.direction), (COMPARABLE, None, "증가"))

    def test_missing_currency_needs_review(self):
        for currencies in ((None, None), ("", ""), ("KRW", None)):
            with self.subTest(currencies=currencies):
                result = compare(fact(120, currency=currencies[0]), fact(100, quarter(2024, 9), currency=currencies[1]))
                self.assertEqual((result.status, result.change), (NEEDS_REVIEW, 20))
                self.assertIn("통화가 확인되지 않았다", result.reasons)

    def test_name_conflict_needs_review_but_shows_the_numbers(self):
        conflicted = replace(fact(120), resolved_by=NAME_CONFLICT, notes=("다른 표준계정ID로 표기됨",))
        result = compare(conflicted, fact(100, quarter(2024, 9)))
        self.assertEqual((result.status, result.change, result.reasons), (NEEDS_REVIEW, 20, ("다른 표준계정ID로 표기됨",)))

    def test_two_reports_without_a_basis_check_need_review(self):
        result = compare(fact(120, rcept="20251114000001"), fact(100, quarter(2024, 9), rcept="20241114000001"))
        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertIn("확인하지 않았다", result.reasons[0])

    def test_two_reports_with_a_basis_check(self):
        current = fact(120, rcept="20251114000001")
        base = fact(100, quarter(2024, 9), rcept="20241114000001")
        linked = compare(current, base, BasisCheck(linked=True))
        self.assertEqual(linked.status, COMPARABLE)
        self.assertTrue(any("모두 일치" in note for note in linked.notes))
        unlinked = compare(current, base, BasisCheck(linked=False))
        self.assertEqual(unlinked.status, NEEDS_REVIEW)
        self.assertIn("함께 나오는 값이 없어", unlinked.reasons[0])
        gap = compare(current, base, BasisCheck(linked=False, gaps=("2024년 사업보고서가 캐시에 없어",)))
        self.assertEqual(gap.reasons, ("2024년 사업보고서가 캐시에 없어",))

    def test_restatement_between_two_reports_needs_review(self):
        current = fact(120, rcept="20251114000001")
        base = fact(100, quarter(2024, 9), rcept="20241114000001")
        restatements = find_restatements([fact(90, instant(2023, 12), rcept="20241114000001"),
                                          fact(95, instant(2023, 12), rcept="20250317000001")])
        self.assertEqual(len(restatements), 1)
        result = compare(current, base, BasisCheck(tuple(restatements), linked=True))
        self.assertEqual((result.status, result.change), (NEEDS_REVIEW, 20))
        self.assertIn("재작성", result.reasons[0])
        self.assertIn("영향은 확인하지 못했다", result.reasons[0])

    def test_restatement_inside_one_report_is_only_noted(self):
        current = fact(120, rcept="20251114000001")
        base = fact(100, quarter(2024, 9), rcept="20251114000001")
        earlier = fact(110, quarter(2024, 9), rcept="20241114000001")
        result = compare(current, base, BasisCheck(tuple(find_restatements([earlier, base])), linked=True))
        self.assertEqual((result.status, result.change_pct), (COMPARABLE, Decimal("20.00")))
        self.assertTrue(any("같은 보고서의 값을 쓴다" in note for note in result.notes))

    def test_restatements_need_the_same_currency(self):
        self.assertEqual(find_restatements([fact(90, instant(2023, 12), rcept="1"),
                                            fact(95, instant(2023, 12), rcept="2", currency="USD")]), [])


class ReviewTests(unittest.TestCase):
    """review_change on a small synthetic cache (offline, no key)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = ResponseCache(Path(temp.name))
        self.client = DartClient(self.cache, key_loader=self.no_key, offline=True)

    @staticmethod
    def no_key():
        raise AssertionError("must not need the key")

    def store(self, year, report, rows=None, status="000", **amounts):
        if rows is None:
            rows = [row("BS", "ifrs-full_Assets", "자산총계", year=year, report=report, **amounts)] if status == "000" else []
        body = json.dumps({"status": status, "message": "", "list": rows}, ensure_ascii=False)
        params = {"corp_code": CORP, "bsns_year": str(year), "reprt_code": report, "fs_div": "CFS"}
        self.cache.put("fnlttSinglAcntAll.json", params, body.encode("utf-8"), status, "", "2026-10-07T00:00:00+00:00")

    def review(self):
        return review_change(self.client, CORP, "CFS", "total_assets", instant(2025, 9), instant(2024, 9))

    def store_quarters(self):
        self.store(2025, "11014", thstrm="120", frmtrm="110")
        self.store(2024, "11014", thstrm="100", frmtrm="90")

    def test_linked_reports_are_comparable(self):
        self.store_quarters()
        self.store(2024, "11011", thstrm="110", frmtrm="90", bfefrmtrm="80")
        result = self.review()
        self.assertEqual((result.status, result.change), (COMPARABLE, 20))

    def test_restatement_found_through_the_bridge_report(self):
        self.store_quarters()
        self.store(2024, "11011", thstrm="110", frmtrm="95", bfefrmtrm="80")
        result = self.review()
        self.assertEqual((result.status, result.change), (NEEDS_REVIEW, 20))
        self.assertIn("2023-12-31", result.reasons[0])

    def test_an_unusable_bridge_report_needs_review(self):
        cases = {
            "not cached": (lambda: None, "캐시에 없어"),
            "no data": (lambda: self.store(2024, "11011", status="013"), "013"),
            "no account": (lambda: self.store(2024, "11011", rows=[row("BS", "ifrs-full_Liabilities", "부채총계", year=2024,
                                                                         report="11011", thstrm="1")]), "계정 값을 쓸 수 없어"),
        }
        for label, (prepare, text) in cases.items():
            with self.subTest(label):
                self.setUp()
                self.store_quarters()
                prepare()
                result = self.review()
                self.assertEqual((result.status, result.change), (NEEDS_REVIEW, 20))
                self.assertIn(text, result.reasons[0])

    def store_income(self, year, report, **amounts):
        self.store(year, report, rows=[row("IS", "ifrs-full_Revenue", "매출액", year=year, report=report, **amounts)])

    def quarter_over_quarter(self):
        return review_change(self.client, CORP, "CFS", "revenue", quarter(2025, 9), quarter(2025, 6))

    def test_quarters_of_one_year_are_linked_through_the_year_to_date(self):
        self.store_income(2025, "11014", thstrm="30", thstrm_add="90", frmtrm_q="20", frmtrm_add="70")
        self.store_income(2025, "11012", thstrm="25", thstrm_add="60", frmtrm_q="22", frmtrm_add="50")
        self.assertEqual(self.quarter_over_quarter().status, COMPARABLE)

    def test_quarters_whose_year_to_date_disagree_need_review(self):
        self.store_income(2025, "11014", thstrm="30", thstrm_add="90", frmtrm_q="20", frmtrm_add="70")
        self.store_income(2025, "11012", thstrm="25", thstrm_add="61", frmtrm_q="22", frmtrm_add="50")
        result = self.quarter_over_quarter()
        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertIn("2025-01-01~2025-06-30", result.reasons[0])

    def test_quarters_without_a_shared_value_need_review(self):
        self.store_income(2025, "11014", thstrm="30", thstrm_add="", frmtrm_q="20", frmtrm_add="")
        self.store_income(2025, "11012", thstrm="25", thstrm_add="60", frmtrm_q="22", frmtrm_add="50")
        result = self.quarter_over_quarter()
        self.assertEqual(result.status, NEEDS_REVIEW)
        self.assertIn("함께 나오는 값이 없어", result.reasons[0])


if __name__ == "__main__":
    unittest.main()
