"""The scorer tells apart a correct answer, a wrong number, a basis mix-up, and an ungrounded number.

Uses only the committed gold file and hand-written tool results, so it runs without the cache.
"""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from scoring import score_case, summarize  # noqa: E402

GOLD = {answer["id"]: answer for answer in json.loads((ROOT / "eval" / "dev_gold.json").read_text(encoding="utf-8"))["answers"]}
QUESTIONS = {question["id"]: question["question"]
             for question in json.loads((ROOT / "eval" / "dev_questions.json").read_text(encoding="utf-8"))["questions"]}

# what the model saw for dev01 (the compare_values result for the right reading)
DEV01_SEEN = [{
    "tool": "compare_values", "company": "삼성전자", "basis": "연결", "account": "revenue", "status": "비교 가능",
    "current": {"period": {"start": "2025-01-01", "end": "2025-12-31"}, "amount": 333_605_938_000_000, "rcept_no": "20260310002820"},
    "base": {"period": {"start": "2024-01-01", "end": "2024-12-31"}, "amount": 300_870_903_000_000, "rcept_no": "20260310002820"},
    "change": 32_735_035_000_000, "change_pct": "10.88", "direction": "증가", "reasons": [], "notes": [],
}]
DEV01_CORRECT = {
    "status": "비교 가능", "company": "삼성전자", "account": "revenue",
    "values": [{"basis": "연결", "start": "2025-01-01", "end": "2025-12-31", "amount": 333_605_938_000_000},
               {"basis": "연결", "start": "2024-01-01", "end": "2024-12-31", "amount": 300_870_903_000_000}],
    "change": 32_735_035_000_000, "change_pct": "10.88",
    "answer": "연결 기준 2025년 매출액은 333조 6,059억 원으로 2024년(300.9조 원)보다 32조 7,350억 원(10.88%) 늘었습니다.",
    "clarifying_question": None,
}


def score(question_id, answer, seen=DEV01_SEEN):
    return score_case(GOLD[question_id], answer, seen, QUESTIONS[question_id])


def edited(**changes):
    answer = copy.deepcopy(DEV01_CORRECT)
    answer.update(changes)
    return answer


class DistinguishTests(unittest.TestCase):
    """Completion criterion of roadmap 1-4."""

    def test_correct_answer(self):
        result = score("dev01", DEV01_CORRECT)
        self.assertTrue(result.passed, result.problems)
        self.assertEqual((result.numbers_ok, result.basis_ok, result.ungrounded), (True, True, []))

    def test_wrong_number(self):
        result = score("dev01", edited(change_pct="10.89", answer="연결 기준 2025년 매출액은 333.6조 원으로 10.89% 늘었습니다."))
        self.assertFalse(result.passed)
        self.assertFalse(result.numbers_ok)
        self.assertTrue(result.basis_ok)
        self.assertIn("10.89%", result.ungrounded)

    def test_basis_mix_up_with_numbers_it_was_shown(self):
        # dev04 asks for Jan-Sep; the model compared the three-month quarters it fetched instead
        seen = [{"tool": "compare_values", "company": "셀트리온", "basis": "연결", "account": "operating_income",
                 "status": "비교 가능", "current": {"period": {"start": "2025-07-01", "end": "2025-09-30"}, "amount": 301_411_957_351},
                 "base": {"period": {"start": "2024-07-01", "end": "2024-09-30"}, "amount": 207_686_368_229},
                 "change": 93_725_589_122, "change_pct": "45.13"}]
        answer = {"status": "비교 가능", "company": "셀트리온", "account": "operating_income",
                  "values": [{"basis": "연결", "start": "2025-07-01", "end": "2025-09-30", "amount": 301_411_957_351},
                             {"basis": "연결", "start": "2024-07-01", "end": "2024-09-30", "amount": 207_686_368_229}],
                  "change": 93_725_589_122, "change_pct": "45.13",
                  "answer": "연결 기준 2025년 3분기 영업이익은 3,014억 원으로 전년 같은 분기보다 45.13% 늘었습니다.",
                  "clarifying_question": None}
        result = score("dev04", answer, seen)
        self.assertFalse(result.passed)
        self.assertFalse(result.basis_ok)
        self.assertEqual(result.ungrounded, [])  # every number came from what it was shown

    def test_ungrounded_number(self):
        result = score("dev01", edited(answer=DEV01_CORRECT["answer"] + " 영업이익률로 보면 12.3% 수준입니다."))
        self.assertFalse(result.passed)
        self.assertEqual((result.numbers_ok, result.basis_ok), (True, True))
        self.assertEqual(result.ungrounded, ["12.3%"])

    def test_ungrounded_structured_amount(self):
        values = copy.deepcopy(DEV01_CORRECT["values"])
        values[1]["amount"] = 300_000_000_000_000
        result = score("dev01", edited(values=values))
        self.assertFalse(result.numbers_ok)
        self.assertIn("values[1].amount=300000000000000", result.ungrounded)


class OtherFailureTests(unittest.TestCase):
    def test_format_errors(self):
        for raw in ("not json", "{}", json.dumps(edited(status="좋음")), json.dumps(edited(change_pct=10.88)), None):
            with self.subTest(raw=raw):
                result = score("dev01", raw)
                self.assertTrue(result.format_error)
                self.assertFalse(result.passed)

    def test_wrong_status_but_right_decision(self):
        result = score("dev01", edited(status="확인 필요"))
        self.assertEqual((result.status_ok, result.decision_ok, result.passed), (False, True, False))

    def test_false_refusal(self):
        result = score("dev01", edited(status="비교 불가", values=[], change=None, change_pct=None, answer="비교할 수 없습니다."))
        self.assertEqual((result.decision_ok, result.numbers_ok, result.passed), (False, False, False))

    def test_extra_value_from_another_basis(self):
        values = DEV01_CORRECT["values"] + [{"basis": "별도", "start": "2025-01-01", "end": "2025-12-31", "amount": 333_605_938_000_000}]
        self.assertFalse(score("dev01", edited(values=values)).basis_ok)

    def test_refusal_must_not_carry_numbers(self):
        seen = [{"tool": "compare_values", "status": "비교 불가", "reasons": ["현금흐름표는 연초부터의 누적 값만 제공한다"],
                 "current": None, "base": None, "change": None, "change_pct": None}]
        good = {"status": "비교 불가", "company": "삼성전자", "account": "operating_cash_flow", "values": [], "change": None,
                "change_pct": None, "clarifying_question": None,
                "answer": "현금흐름표는 연초부터의 누적 값만 제공해서 7~9월 3개월 값은 비교할 수 없습니다. 1~9월 누적 비교는 가능합니다."}
        self.assertTrue(score("dev10", good, seen).passed)
        # passing the 9-month cumulative figure off as the quarter: a number the tool never gave for this question
        bad = {**good, "answer": "3분기 영업활동현금흐름은 56조 5,155억 원입니다."}
        result = score("dev10", bad, seen)
        self.assertFalse(result.passed)
        self.assertEqual(result.ungrounded, ["56조 5,155억 원"])

    def test_clarification_must_name_both_candidates_and_not_answer(self):
        base = {"status": "되묻기", "company": "셀트리온", "account": None, "values": [], "change": None, "change_pct": None}
        good = {**base, "answer": "어떤 이익인지 알려 주세요.", "clarifying_question": "영업이익과 당기순이익 중 어느 것을 비교할까요?"}
        self.assertTrue(score("dev12", good, []).passed)
        one = {**base, "answer": "확인이 필요합니다.", "clarifying_question": "영업이익을 말씀하시나요?"}
        self.assertFalse(score("dev12", one, []).refusal_ok)
        picked = {**base, "status": "비교 가능", "answer": "영업이익 기준으로 답합니다.", "clarifying_question": None}
        self.assertFalse(score("dev12", picked, []).decision_ok)

    def test_side_by_side_must_not_report_a_change(self):
        values = [{"basis": "연결", "start": "2025-01-01", "end": "2025-12-31", "amount": 333_605_938_000_000},
                  {"basis": "별도", "start": "2025-01-01", "end": "2025-12-31", "amount": 238_043_009_000_000}]
        seen = [{"tool": "side_by_side", "values": [{"amount": 333_605_938_000_000}, {"amount": 238_043_009_000_000}],
                 "difference": 95_562_929_000_000, "period": {"start": "2025-01-01", "end": "2025-12-31"}}]
        good = {"status": "나란히 표시", "company": "삼성전자", "account": "revenue", "values": values, "change": None,
                "change_pct": None, "clarifying_question": None,
                "answer": "2025년 연결 매출은 333.6조 원, 별도 매출은 238.0조 원으로 연결이 95.6조 원 큽니다. 집계 범위의 차이입니다."}
        self.assertTrue(score("dev05", good, seen).passed)
        as_change = {**good, "change": 95_562_929_000_000}
        self.assertFalse(score("dev05", as_change, seen).numbers_ok)
        worded = {**good, "answer": good["answer"] + " 연결이 별도보다 증가했습니다."}
        result = score("dev05", worded, seen)
        self.assertEqual(result.warnings, ["증가"])
        self.assertTrue(result.passed)  # a warning is recorded for a human, not an automatic failure


class WordingAndCompanyTests(unittest.TestCase):
    SEEN = [{"tool": "compare_values", "status": "비교 가능",
             "current": {"period": {"start": "2025-01-01", "end": "2025-12-31"}, "amount": 517_959_587_282},
             "base": {"period": {"start": "2024-01-01", "end": "2024-12-31"}, "amount": -161_870_567_171},
             "change": 679_830_154_453, "change_pct": None, "direction": "흑자 전환"}]
    ANSWER = {"status": "비교 가능", "company": "카카오", "account": "net_income",
              "values": [{"basis": "연결", "start": "2025-01-01", "end": "2025-12-31", "amount": 517_959_587_282},
                         {"basis": "연결", "start": "2024-01-01", "end": "2024-12-31", "amount": -161_870_567_171}],
              "change": 679_830_154_453, "change_pct": None, "clarifying_question": None,
              "answer": "연결 기준 당기순이익은 2024년 1,619억 원 손실에서 2025년 5,180억 원 이익으로 흑자전환했습니다."}

    def test_sign_change_must_be_named(self):
        self.assertTrue(score("dev09", self.ANSWER, self.SEEN).passed)
        silent = {**self.ANSWER, "answer": "연결 기준 당기순이익은 2025년 5,180억 원입니다."}
        result = score("dev09", silent, self.SEEN)
        self.assertEqual((result.wording_ok, result.passed), (False, False))

    def test_company_suffixes_are_ignored(self):
        self.assertTrue(score("dev01", edited(company="삼성전자(주)")).basis_ok)
        self.assertFalse(score("dev01", edited(company="삼성SDI")).basis_ok)


class SummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        cases = [{"score": score("dev01", DEV01_CORRECT).to_dict(), "model_requests": 1, "latency_ms": 100.0},
                 {"score": score("dev01", "not json").to_dict(), "model_requests": 1, "latency_ms": 300.0}]
        summary = summarize(cases)
        self.assertEqual(summary["passed"], {"correct": 1, "total": 2})
        self.assertEqual(summary["format_errors"], 1)
        self.assertEqual(summary["model_requests"], 2)
        self.assertEqual(summary["latency_ms"], {"total": 400.0, "median_per_case": 200.0})


if __name__ == "__main__":
    unittest.main()
