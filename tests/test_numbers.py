"""Tests for finding numbers in Korean answers and checking them against tool results."""

from decimal import Decimal
import unittest

from dart_review.numbers import allowed_from, check_text, extract, ungrounded

TOOL_RESULT = {
    "status": "비교 가능",
    "current": {"period": {"start": "2025-01-01", "end": "2025-12-31"}, "amount": 333_605_938_000_000,
                "rcept_no": "20260310002820"},
    "base": {"period": {"start": "2024-01-01", "end": "2024-12-31"}, "amount": 300_870_903_000_000,
             "rcept_no": "20260310002820"},
    "change": 32_735_035_000_000,
    "change_pct": "10.88",
    "notes": ["2023-12-31 시점 값이 보고서마다 다르다(재작성): 접수번호 20241114002862에서 2,230,608,519,706"],
}
QUESTION = "삼성전자 2025년 매출액이 전년보다 얼마나 늘었어?"


def bad(text, *sources):
    allowed = allowed_from(*(sources or (TOOL_RESULT, QUESTION)))
    return [mention.text for mention in ungrounded(check_text(text, allowed))]


class ExtractTests(unittest.TestCase):
    def kinds(self, text):
        return [(mention.kind, mention.value) for mention in extract(text)]

    def test_korean_amounts(self):
        self.assertEqual(self.kinds("333조 6,059억 원"), [("amount", Decimal("333605900000000"))])
        self.assertEqual(self.kinds("300.9조"), [("amount", Decimal("300900000000000"))])
        self.assertEqual(self.kinds("5천만 원"), [("amount", Decimal("50000000"))])
        self.assertEqual(self.kinds("2,431,791,719,869원"), [("amount", Decimal("2431791719869"))])
        self.assertEqual(self.kinds("△1,494억 원"), [("amount", Decimal("149400000000"))])

    def test_precision_follows_the_last_written_digit(self):
        units = {mention.text: mention.unit for mention in extract("333.6조, 333조 6,059억 원, 1,234원, 10.9%")}
        self.assertEqual(units, {"333.6조": Decimal("1E11"), "333조 6,059억 원": Decimal("1E8"), "1,234원": 1, "10.9%": Decimal("0.1")})

    def test_dates_and_calendar_words(self):
        kinds = [mention.kind for mention in extract("2025-09-30 시점, 2024년 3분기, 1~9월, 12개월, 9월 30일, 제 57 기")]
        self.assertEqual(kinds.count("year"), 2)
        self.assertNotIn("amount", kinds)
        self.assertNotIn("unparsed", kinds)

    def test_words_starting_with_won_are_not_currency(self):
        self.assertEqual(self.kinds("원인은 모른다. 3 원래 값"), [])

    def test_small_counts_are_ignored_and_bare_decimals_are_unparsed(self):
        self.assertEqual(self.kinds("두 보고서, 2개 계정"), [])
        self.assertEqual(self.kinds("10.88"), [("unparsed", None)])

    def test_nothing_is_counted_twice(self):
        self.assertEqual(len(extract("10.88%")), 1)
        self.assertEqual(len(extract("20251114002447")), 1)


class GroundingTests(unittest.TestCase):
    def test_faithful_answer_has_no_ungrounded_numbers(self):
        text = ("2025년 연결 매출은 333조 6,059억 원(333,605,938,000,000원)으로, 2024년 300.9조 원보다 "
                "32조 7,350억 원(10.88%) 늘었다. 접수번호 20260310002820, 2025-01-01~2025-12-31 (누적 12개월).")
        self.assertEqual(bad(text), [])

    def test_rounding_and_truncation_are_accepted(self):
        self.assertEqual(bad("약 334조 원, 333조 원, 10.9%, 11%, 10%"), [])

    def test_numbers_outside_the_written_precision_are_ungrounded(self):
        self.assertEqual(bad("335조 원, 12%, 10.7%"), ["12%", "10.7%", "335조 원"])  # 10.8% would be a truncation of 10.88%

    def test_self_computed_numbers_are_ungrounded(self):
        # a ratio and a share the tool never gave
        self.assertEqual(bad("연결이 별도의 1.4배이고, 별도 비중은 71.4%다"), ["71.4%", "1.4배"])

    def test_wrong_year_and_unknown_receipt(self):
        self.assertEqual(bad("2026년 매출, 접수번호 20251114000001"), ["20251114000001", "2026년"])

    def test_numbers_inside_tool_notes_are_allowed(self):
        self.assertEqual(bad("2023-12-31 값은 접수번호 20241114002862에서 2조 2,306억 원이었다"), [])

    def test_bare_amount_must_match_exactly(self):
        self.assertEqual(bad("333,605,938,000,000"), [])
        self.assertEqual(bad("333,605,938,000,001"), ["333,605,938,000,001"])

    def test_sign_is_ignored(self):
        allowed = {"change": -149_459_639_855, "change_pct": "-6.92"}
        self.assertEqual(bad("1,494억 원 감소(6.92%)", allowed), [])
        self.assertEqual(bad("−1,494억 원(−6.92%)", allowed), [])

    def test_amount_without_separators_is_not_a_receipt(self):
        # Codex 1-5 review: a 14-digit amount was read as an unknown receipt number
        self.assertEqual(bad("변화는 32735035000000원, 매출 333605938000000"), [])
        self.assertEqual(bad("접수번호 20260310002820"), [])
        self.assertEqual(bad("32735035000001"), ["32735035000001"])

    def test_a_rate_never_grounds_a_multiple_or_points(self):
        # Codex 1-5 review: "10.88배" passed against the rate 10.88%
        self.assertEqual(bad("10.88배 늘었다"), ["10.88배"])
        self.assertEqual(bad("10.88%p 늘었다"), ["10.88%p"])
        self.assertEqual(bad("10.88% 늘었다"), [])
        self.assertEqual(bad("1.4배", {"note": "연결이 별도의 1.4배"}), [])

    def test_only_rounding_or_truncation_counts(self):
        # Codex 1-5 review E4: a value one step past both rounding and truncation is not grounded
        self.assertEqual(bad("1.3조 원", {"a": 1_240_000_000_000}), ["1.3조 원"])
        self.assertEqual(bad("1.2조 원", {"a": 1_240_000_000_000}), [])
        self.assertEqual(bad("1.1조 원", {"a": 1_190_000_000_000}), [])  # truncation
        self.assertEqual(bad("약 3,276억 원", {"a": 327_543_643_155}), ["3,276억 원"])
        self.assertEqual(bad("약 3,276억 원", {"a": 327_560_000_000}), [])
        self.assertEqual(bad("약 4조 원", {"a": 3_275_436_431_552}), ["4조 원"])
        self.assertEqual(bad("3.3조 원", {"a": 3_275_436_431_552}), [])
        self.assertEqual(bad("10.9%", {"change_pct": "10.81"}), ["10.9%"])

    def test_magnitudes_are_read_or_flagged(self):
        # Codex 1-5 review E5: "9백억" was silently dropped and the rest passed
        self.assertEqual(bad("1조 9백억 원", {"a": 1_020_000_000_000}), ["1조 9백억 원"])
        self.assertEqual(bad("1조 2백억 원", {"a": 1_020_000_000_000}), [])
        self.assertEqual(bad("3억 2천만 원", {"a": 320_000_000}), [])
        self.assertIn("1천", bad("1천2백억 원", {"a": 120_000_000_000}))

    def test_a_receipt_number_written_as_money_is_money(self):
        self.assertEqual(bad("매출액은 20260310002820원입니다"), ["20260310002820원"])

    def test_date_notations(self):
        source = {"period": {"end": "2025-09-30"}}
        for text in ("2025-09-30", "2025.09.30", "2025/09/30", "20250930 기준", "2025년 9월 30일"):
            with self.subTest(text=text):
                self.assertEqual(bad(text, source), [])
        self.assertEqual(bad("2025-02-31", source), ["2025-02-31"])
        self.assertEqual(bad("2026.09.30", source), ["2026.09.30"])

    def test_error_results_ground_nothing(self):
        # Codex 1-5 review E2: an echoed tool name must not launder a number
        self.assertEqual(bad("영업이익률은 99.9%", {"error": "알 수 없는 도구: unknown_영업이익률99.9%"}), ["99.9%"])

    def test_the_question_grounds_years_only(self):
        from dart_review.numbers import question_years
        self.assertEqual(question_years("2025년 매출이 999조 원이라던데 맞아? 10% 늘었어?"), {2025})

    def test_unparsed_numbers_count_as_ungrounded(self):
        self.assertEqual(bad("변화율은 10.88"), ["10.88"])


if __name__ == "__main__":
    unittest.main()
