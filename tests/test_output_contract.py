"""Output contract fixes from the 2026-10-08 Codex review (docs/reviews/roadmap_proposal_codex_response.ko.md).

Each test pins one counterexample the review reproduced: a legitimate
확인 필요 result must render, and an amount is called 원 only when the
filing says KRW.
"""

import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dart_review import crosscheck, demo  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.crosscheck import ungrounded_in_answer  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402
from dart_review.render import format_amount, markdown_report, structured_answer  # noqa: E402
from test_crosscheck import model_reading  # noqa: E402

YEAR = {"start": "2025-01-01", "end": "2025-12-31", "label": "2025년 연간"}
PRIOR = {"start": "2024-01-01", "end": "2024-12-31", "label": "2024년 연간"}


def fact(amount, period=YEAR, currency="KRW", basis="연결"):
    return {"basis": basis, "period": period, "amount": amount, "currency": currency,
            "report": "2025년 사업보고서", "rcept_no": "20260310000001", "account_nm": "매출액"}


def comparison(current, base, status="확인 필요", change=None, reasons=("매출액 후보가 여러 개다",)):
    return {"tool": "compare_values", "company": "삼성전자", "basis": "연결", "account": "revenue",
            "account_label": "매출액", "requested": {"current": YEAR, "base": PRIOR}, "status": status,
            "reasons": list(reasons), "notes": [], "current": current, "base": base, "change": change,
            "change_pct": None, "direction": "증가" if change else None}


class NeedsReviewRenderTests(unittest.TestCase):
    """B3: a value with several candidate rows has no amount; the renderer used to crash on it."""

    def test_missing_amount_is_named_not_formatted(self):
        result = comparison(fact(None), fact(100 * 10 ** 8, PRIOR))
        answer = structured_answer(result)
        self.assertIn("2025년 연간(1~12월) 값은 확정하지 못했습니다", answer["answer"])
        self.assertIn("2024년 연간(1~12월) 100억 원", answer["answer"])
        self.assertIsNone(answer["change"])
        self.assertNotIn("증가", answer["answer"])
        report = markdown_report(answer, result)
        self.assertNotIn("**변화:**", report)
        self.assertEqual(ungrounded_in_answer(answer, [result], "삼성전자 2025년 매출"), [])

    def test_both_amounts_missing(self):
        answer = structured_answer(comparison(fact(None), fact(None, PRIOR)))
        self.assertIn("2025년 연간(1~12월), 2024년 연간(1~12월) 값은 확정하지 못했습니다", answer["answer"])


class CurrencyRenderTests(unittest.TestCase):
    """B3: only a KRW amount is written in 원."""

    def test_format_amount(self):
        self.assertEqual(format_amount(333_605_938_000_000, "KRW"), "333조 6,059억 원")
        self.assertEqual(format_amount(238_043_000_000_000, "USD"), "238,043,000,000,000 (USD 단위)")
        self.assertEqual(format_amount(1_000, None), "1,000 (통화 미확인)")

    def test_side_by_side_with_two_currencies(self):
        result = {"tool": "side_by_side", "company": "삼성전자", "account": "revenue", "account_label": "매출액",
                  "period": YEAR, "status": "확인 필요", "reasons": ["통화가 달라(KRW, USD) 차이를 계산하지 않았다"],
                  "values": [fact(100 * 10 ** 12), fact(238_043_000_000_000, currency="USD", basis="별도")],
                  "difference": None}
        answer = structured_answer(result)
        self.assertIn("연결 100조 원", answer["answer"])
        self.assertIn("별도 238,043,000,000,000 (USD 단위)", answer["answer"])
        self.assertNotIn("238조", answer["answer"])
        report = markdown_report(answer, result)
        self.assertNotIn("금액(원)", report)
        self.assertIn("| 238,043,000,000,000 USD |", report)

    def test_unknown_currency_change(self):
        result = comparison(fact(120 * 10 ** 8, currency=None), fact(100 * 10 ** 8, PRIOR, currency=None),
                            change=20 * 10 ** 8, reasons=("통화가 확인되지 않았다",))
        result["change_pct"] = "20.00"
        answer = structured_answer(result)
        self.assertNotIn("원", answer["answer"].replace("확인이 필요합니다", ""))
        self.assertIn("2,000,000,000 (통화 미확인)(20.00%) 증가", answer["answer"])
        self.assertIn("**변화:** 2,000,000,000 (통화 미확인) (20.00%, 증가)", markdown_report(answer, result))

    def test_krw_output_unchanged(self):
        result = comparison(fact(333_605_938_000_000), fact(300_870_903_000_000, PRIOR), status="비교 가능",
                            change=32_735_035_000_000, reasons=())
        result["change_pct"] = "10.88"
        answer = structured_answer(result)
        self.assertIn("2025년 연간(1~12월) 333조 6,059억 원, 2024년 연간(1~12월) 300조 8,709억 원.", answer["answer"])
        self.assertIn("| 금액(원) |", markdown_report(answer, result))
        self.assertIn("**변화:** 32,735,035,000,000원 (10.88%, 증가)", markdown_report(answer, result))


def no_key():
    raise AssertionError("must not need the key")


class FinalBoundaryTests(unittest.TestCase):
    """B6/C2: what is shown is checked as shown, including the clarifying question of a disagreement."""

    def setUp(self):
        self.client = DartClient(ResponseCache(demo.DEMO_DIR / "opendart"), key_loader=no_key, offline=True)
        self.question = demo.DEMO_QUESTIONS[0]  # 삼성전자 2025년 매출액 vs 전년

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def ask(self, reading):
        return demo.answer(self.question, self.client, ScriptedChat([Reply(json.dumps(reading, ensure_ascii=False))]))

    def test_a_number_added_after_the_text_check_is_withheld(self):
        original = demo.markdown_report
        with mock.patch.object(demo, "markdown_report", lambda answer, result: original(answer, result) + "\n영업이익률은 99.9%입니다.\n"):
            shown = self.ask(model_reading("dev01"))
        self.assertEqual(shown["withheld"], ["99.9%"])
        self.assertIsNone(shown["report"])
        self.assertIsNone(shown["answer"])

    def test_a_disagreement_shows_proposed_years_but_no_figures(self):
        shown = self.ask(model_reading("dev01", base_period={"kind": "year_to_date", "year": 2019, "month": 12}))
        self.assertIsNone(shown["withheld"])
        self.assertIn("2019년 연간", shown["report"])  # a proposed reading, labeled as such
        original = crosscheck.disagreement_answer

        def with_a_figure(company, first, second):
            answer = original(company, first, second)
            return {**answer, "answer": answer["answer"] + " 매출은 333조 원입니다."}

        with mock.patch.object(crosscheck, "disagreement_answer", with_a_figure):
            shown = self.ask(model_reading("dev01", base_period={"kind": "year_to_date", "year": 2019, "month": 12}))
        self.assertEqual(shown["withheld"], ["333조 원"])


if __name__ == "__main__":
    unittest.main()
