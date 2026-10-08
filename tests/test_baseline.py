"""The keyword baseline's rules, on sentences that are not in the evaluation sets."""

from datetime import date
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review.baseline import default_year_note, latest_annual_year, read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402


REFERENCE = date(2026, 10, 8)


def period(kind, year, month):
    return {"kind": kind, "year": year, "month": month}


class ReadingTests(unittest.TestCase):
    def arguments(self, text):
        """The reading's arguments, with a lookup's period under current_period (period parsing is the same)."""
        reading = read(text, REFERENCE)
        self.assertIn(reading.kind, ("compare", "lookup"), reading.reason)
        arguments = dict(reading.arguments)
        if reading.kind == "lookup":
            arguments["current_period"] = arguments.pop("period")
        return arguments

    def test_company_basis_and_account(self):
        arguments = self.arguments("카카오 별도 부채 2024년 수준이 궁금해")
        self.assertEqual((arguments["company"], arguments["basis"], arguments["account"]), ("카카오", "별도", "total_liabilities"))
        self.assertEqual(self.arguments("셀트리온 2024년 영업수익")["account"], "revenue")
        self.assertEqual(self.arguments("삼성전자 2024년 영업활동 현금흐름")["account"], "operating_cash_flow")

    def test_unknown_company_and_missing_parts(self):
        self.assertEqual(read("네이버 2024년 매출").kind, "unreadable")  # sealed companies are not in the development list
        # since EVAL_DESIGN 12 a question without a year is read for the latest annual report year
        self.assertEqual(self.arguments("카카오 매출")["current_period"], period("year_to_date", 2025, 12))
        self.assertEqual(read("카카오 2024년 직원 수").reason, "계정을 찾지 못함")

    def test_bare_profit_asks_back(self):
        reading = read("카카오 2024년 이익 알려줘")
        self.assertEqual((reading.kind, reading.options), ("clarify", ("operating_income", "net_income")))
        self.assertEqual(self.arguments("카카오 2024년 순이익")["account"], "net_income")

    def test_unsupported_accounts_are_refused_not_narrowed(self):
        # review B7/C1: a supported keyword inside a longer account name is not that account
        cases = {"삼성전자 2025년 투자활동현금흐름 전년 대비": "투자활동현금흐름", "카카오 2025년 유동자산": "유동자산",
                 "셀트리온 2025년 매출원가가 늘었어?": "매출원가", "카카오 2025년 기타비유동부채": "기타비유동부채",
                 "삼성전자 2025년 계속영업당기순이익": "계속영업당기순이익", "카카오 2025년 자본총계": "자본총계",
                 "셀트리온 작년 이익잉여금": "이익잉여금"}
        for text, term in cases.items():
            with self.subTest(text=text):
                reading = read(text)
                self.assertEqual((reading.kind, reading.arguments), ("unsupported", {"term": term, "scope": "account"}))
        # supported names that contain other keywords stay supported
        for text, account in {"삼성전자 2025년 자산총계": "total_assets", "삼성전자 2025년 총자산": "total_assets",
                              "카카오 2025년 영업현금흐름": "operating_cash_flow", "카카오 2025년 당기순이익(손실)": "net_income",
                              "카카오 2025년 연결당기순이익": "net_income", "셀트리온 2025년 매출액": "revenue"}.items():
            with self.subTest(text=text):
                self.assertEqual(self.arguments(text)["account"], account)

    def test_years(self):
        arguments = self.arguments("카카오 2023년과 2025년 매출")
        self.assertEqual((arguments["current_period"]["year"], arguments["base_period"]["year"]), (2025, 2023))
        self.assertEqual(self.arguments("카카오 2024년 매출 전년 대비")["base_period"]["year"], 2023)

    def test_balance_sheet_points(self):
        self.assertEqual(self.arguments("카카오 2024년 2분기말 자산")["current_period"], period("instant", 2024, 6))
        self.assertEqual(self.arguments("카카오 2024년 3월 말 부채")["current_period"], period("instant", 2024, 3))
        self.assertEqual(self.arguments("카카오 2024년 자산총계")["current_period"], period("instant", 2024, 12))

    def test_flow_periods(self):
        cases = {"카카오 2024년 1분기까지 매출": period("year_to_date", 2024, 3),
                 "카카오 2024년 2분기 누적 매출": period("year_to_date", 2024, 6),
                 "카카오 2024년 1~3월 매출": period("year_to_date", 2024, 3),
                 "카카오 2024년 4~6월 매출": period("quarter", 2024, 6),
                 "카카오 2024년 6월까지 매출": period("year_to_date", 2024, 6),
                 "카카오 2024년 상반기 매출": period("year_to_date", 2024, 6),
                 "카카오 2024년 2분기 매출": period("quarter", 2024, 6),
                 "카카오 2024년 매출": period("year_to_date", 2024, 12)}
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.arguments(text)["current_period"], expected)

    def test_previous_quarter(self):
        self.assertEqual(self.arguments("카카오 2024년 1분기 매출, 직전 분기 대비")["base_period"], period("quarter", 2023, 12))
        self.assertEqual(self.arguments("카카오 2024년 2분기 매출, 전 분기 대비")["base_period"], period("quarter", 2024, 3))

    def test_lookup_or_comparison(self):
        # EVAL_DESIGN 12.2: no comparison word and at most one year is a lookup
        for text in ("삼성전자 2025년 매출 알려줘", "카카오 영업이익 부탁해", "셀트리온 2025년 3분기말 부채", "오늘 기준 삼성전자 매출"):
            with self.subTest(text=text):
                self.assertEqual(read(text, REFERENCE).kind, "lookup")
        for text in ("삼성전자 2025년 매출 전년 대비", "카카오 2025년 매출이 늘었어?", "셀트리온 2024년과 2025년 매출",
                     "카카오 2025년 3분기 매출 직전 분기와", "삼성전자 매출 증감"):
            with self.subTest(text=text):
                self.assertEqual(read(text, REFERENCE).kind, "compare")

    def test_relative_and_default_years(self):
        self.assertEqual(self.arguments("셀트리온 작년 영업이익")["current_period"]["year"], 2025)
        self.assertEqual(self.arguments("셀트리온 지난해 영업이익")["current_period"]["year"], 2025)
        self.assertEqual(self.arguments("셀트리온 올해 상반기 영업이익")["current_period"], period("year_to_date", 2026, 6))
        arguments = self.arguments("셀트리온 작년 영업이익을 재작년과 비교해 줘")  # 재작년 is not 작년
        self.assertEqual((arguments["current_period"]["year"], arguments["base_period"]["year"]), (2025, 2024))
        self.assertEqual(self.arguments("셀트리온 2023년 영업이익, 작년과 비교")["current_period"]["year"], 2023)  # four digits win
        # the latest annual report is due by the end of March
        self.assertEqual((latest_annual_year(date(2026, 3, 31)), latest_annual_year(date(2026, 4, 1))), (2024, 2025))
        self.assertEqual(default_year_note("카카오 매출 알려줘", REFERENCE),
                         "연도를 말하지 않아 가장 최근 사업보고서 연도(2025년)로 봤습니다.")
        self.assertIsNone(default_year_note("카카오 작년 매출 알려줘", REFERENCE))

    def test_company_names(self):
        # EVAL_DESIGN 12.3: the longest company name wins
        self.assertEqual(self.arguments("삼전 2025년 매출")["company"], "삼성전자")
        self.assertEqual(self.arguments("삼성 전자 2025년 매출")["company"], "삼성전자")
        for text, term in {"카카오뱅크 2025년 매출 전년 대비": "카카오뱅크", "카카오페이 순이익 알려줘": "카카오페이",
                           "셀트리온제약 2025년 영업이익": "셀트리온제약", "삼성물산 매출": "삼성물산"}.items():
            with self.subTest(text=text):
                reading = read(text, REFERENCE)
                self.assertEqual((reading.kind, reading.arguments), ("unsupported", {"term": term, "scope": "company"}))
        reading = read("카카오와 셀트리온 2025년 매출", REFERENCE)
        self.assertEqual((reading.kind, reading.arguments["scope"]), ("unsupported", "companies"))
        reading = read("삼성 매출 알려줘", REFERENCE)
        self.assertEqual((reading.kind, reading.company, reading.options), ("clarify_company", "삼성", ("삼성전자",)))

    def test_several_accounts_are_out_of_scope(self):
        reading = read("카카오 매출 영업이익 순이익 전부 알려줘", REFERENCE)
        self.assertEqual((reading.kind, reading.arguments), ("unsupported", {"term": "영업이익, 당기순이익, 매출액", "scope": "accounts"}))
        self.assertEqual(read("카카오 2025년 이익 알려줘", REFERENCE).kind, "clarify")  # a bare 이익 still asks back

    def test_side_by_side(self):
        reading = read("카카오 2024년 매출 연결과 별도")
        self.assertEqual((reading.kind, reading.arguments["period"]), ("side_by_side", period("year_to_date", 2024, 12)))


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class BaselineRunTests(unittest.TestCase):
    def test_runs_both_sets_without_a_model_or_the_network(self):
        client = DartClient(ResponseCache(run_eval.CACHE), key_loader=lambda: (_ for _ in ()).throw(AssertionError()), offline=True)
        for question_set in ("dev", "paraphrase"):
            with self.subTest(question_set=question_set):
                cases, summary = run_eval.run("baseline", None, client, question_set=question_set)
                self.assertEqual((summary["cases"], summary["evaluator_errors"], summary["model_attempts"]), (13, 0, 0))
        self.assertEqual(client.network_requests, 0)


if __name__ == "__main__":
    unittest.main()
