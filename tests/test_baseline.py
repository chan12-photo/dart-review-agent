"""The keyword baseline's rules, on sentences that are not in the evaluation sets."""

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review.baseline import read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402


def period(kind, year, month):
    return {"kind": kind, "year": year, "month": month}


class ReadingTests(unittest.TestCase):
    def arguments(self, text):
        reading = read(text)
        self.assertEqual(reading.kind, "compare", reading.reason)
        return reading.arguments

    def test_company_basis_and_account(self):
        arguments = self.arguments("카카오 별도 부채 2024년 수준이 궁금해")
        self.assertEqual((arguments["company"], arguments["basis"], arguments["account"]), ("카카오", "별도", "total_liabilities"))
        self.assertEqual(self.arguments("셀트리온 2024년 영업수익")["account"], "revenue")
        self.assertEqual(self.arguments("삼성전자 2024년 영업활동 현금흐름")["account"], "operating_cash_flow")

    def test_unknown_company_and_missing_parts(self):
        self.assertEqual(read("네이버 2024년 매출").kind, "unreadable")  # sealed companies are not in the development list
        self.assertEqual(read("카카오 매출").reason, "연도를 찾지 못함")
        self.assertEqual(read("카카오 2024년 직원 수").reason, "계정을 찾지 못함")

    def test_bare_profit_asks_back(self):
        reading = read("카카오 2024년 이익 알려줘")
        self.assertEqual((reading.kind, reading.options), ("clarify", ("operating_income", "net_income")))
        self.assertEqual(self.arguments("카카오 2024년 순이익")["account"], "net_income")

    def test_years(self):
        arguments = self.arguments("카카오 2023년과 2025년 매출")
        self.assertEqual((arguments["current_period"]["year"], arguments["base_period"]["year"]), (2025, 2023))
        self.assertEqual(self.arguments("카카오 2024년 매출")["base_period"]["year"], 2023)

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
