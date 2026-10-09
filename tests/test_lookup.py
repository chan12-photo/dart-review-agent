"""Value lookups and company names (docs/EVAL_DESIGN.ko.md section 12) on the development cache.

The gold builder must catch a wrong hand-written expectation and a product
bug, the cross-check must answer lookups and company questions the way the
contract says, and every answer's numbers must be grounded.
"""

import copy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "tests")]

import build_lookup_gold  # noqa: E402
from build_gold import GoldError  # noqa: E402
from dart_review import tools  # noqa: E402
from dart_review.baseline import baseline_turn  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.crosscheck import crosscheck_turn, reading_prompt  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402

CACHE = ROOT / "cache"
REFERENCE = date(2026, 10, 8)
SPEC = json.loads((ROOT / "eval" / "dev_lookup.json").read_text(encoding="utf-8"))
QUESTIONS = {question["id"]: question for question in SPEC["questions"]}


def no_key():
    raise AssertionError("must not need the key")


def record():
    return {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}


def reading(action="lookup", company="삼성전자", basis="연결", account="revenue", period=(2025, 12, "year_to_date"), options=()):
    spec = {"kind": period[2], "year": period[0], "month": period[1]}
    return Reply(json.dumps({"action": action, "company": company, "basis": basis, "account": account,
                             "current_period": spec, "base_period": spec, "clarify_accounts": list(options)}, ensure_ascii=False))


class PromptTests(unittest.TestCase):
    def test_the_default_year_is_computed_into_the_prompt(self):
        prompt = reading_prompt(REFERENCE)
        self.assertIn("연도를 나타내는 말이 전혀 없으면 2025년으로 본다", prompt)
        self.assertIn("기준 날짜는 2026-10-08이다", prompt)
        self.assertNotIn("{", prompt)
        self.assertIn("2024년으로 본다", reading_prompt(date(2026, 3, 31)))


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class GoldBuilderTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)

    def build(self, spec):
        return build_lookup_gold.build(self.client, spec)

    def test_the_committed_gold_is_current(self):
        document, problems = self.build(SPEC)
        self.assertEqual(problems, [])
        committed = json.loads((ROOT / "eval" / "dev_lookup_gold.json").read_text(encoding="utf-8"))
        self.assertEqual(document, committed)

    def test_wrong_expectations_are_caught(self):
        def changed(question_id, change):
            spec = copy.deepcopy(SPEC)
            question = next(item for item in spec["questions"] if item["id"] == question_id)
            change(question["expected"])
            return spec

        cases = {
            "L02 expects a restatement the later report does not show": changed("L02", lambda e: e.update(status="확인 필요")),
            "L06 misses the restatement": changed("L06", lambda e: e.update(status="값 확인")),
            "L01 says no later column, but next year's annual report has one":
                changed("L01", lambda e: e["evidence"]["later_missing"].update(why="no_column")),
            "L07 calls a provided period 조회 불가": changed("L07", lambda e: e["period"].update(month=9)),
            "L03 reads a comparative column": changed("L03", lambda e: e["evidence"]["value"].update(year=2026, column="frmtrm_q")),
        }
        for label, spec in cases.items():
            with self.subTest(label):
                with self.assertRaises(GoldError):
                    self.build(spec)

    def test_product_bugs_are_caught(self):
        with mock.patch.object(tools, "find_restatements", lambda facts: []):
            _, problems = self.build(SPEC)
        self.assertTrue(any(problem.startswith("L05") for problem in problems))
        self.assertTrue(any(problem.startswith("L06") for problem in problems))
        with mock.patch.object(tools, "column_periods", lambda year, report_code, sj_div: {}):
            _, problems = self.build(SPEC)
        self.assertTrue(any(problem.startswith("L02") and "agrees" in problem for problem in problems))


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class LookupAnswerTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def turn(self, question_id, reply):
        rec = record()
        crosscheck_turn(QUESTIONS[question_id]["question"], self.client, rec, ScriptedChat([reply]).chat, REFERENCE)
        return rec

    def test_default_year_lookup(self):
        rec = self.turn("L01", reading())
        self.assertEqual(rec["readings"]["used"], "both")
        answer = rec["answer"]
        self.assertEqual(answer["status"], "값 확인")
        self.assertTrue(answer["answer"].startswith("연도를 말하지 않아 가장 최근 사업보고서 연도(2025년)로 봤습니다."))
        self.assertIn("333조 6,059억 원 (2025년 사업보고서, 접수번호 20260310002820)", answer["answer"])
        self.assertIn("재작성 여부는 확인하지 않았습니다", answer["answer"])
        self.assertEqual((answer["change"], answer["change_pct"]), (None, None))
        self.assertEqual(len(answer["values"]), 1)

    def test_restated_value_shows_both_figures(self):
        rec = self.turn("L05", reading(company="카카오", period=(2023, 9, "quarter")))
        answer = rec["answer"]["answer"]
        self.assertEqual(rec["answer"]["status"], "확인 필요")
        self.assertIn("2조 1,609억 원 (2023년 3분기보고서", answer)
        self.assertIn("같은 기간의 이후 보고서 값: 2조 114억 원 (2024년 3분기보고서", answer)

    def test_a_comparison_reading_of_a_lookup_question_asks_back(self):
        spec = {"kind": "year_to_date", "year": 2025, "month": 12}
        compare = Reply(json.dumps({"action": "compare", "company": "삼성전자", "basis": "연결", "account": "revenue",
                                    "current_period": spec, "base_period": {**spec, "year": 2024}, "clarify_accounts": []}))
        rec = self.turn("L01", compare)
        self.assertEqual(rec["readings"]["used"], "neither (asked back)")
        self.assertIn("값 조회", rec["answer"]["clarifying_question"])

    def test_group_name_is_asked_back_by_both_readers(self):
        rec = self.turn("L10", reading(company="삼성"))
        self.assertEqual(rec["readings"]["used"], "both")
        self.assertEqual(rec["answer"]["status"], "되묻기")
        self.assertIn("말씀하신 회사가 삼성전자인가요?", rec["answer"]["clarifying_question"])
        self.assertEqual(rec["tool_call_count"], 0)

    def test_another_company_is_out_of_scope_whatever_the_model_calls_the_action(self):
        rec = self.turn("L11", reading(action="lookup", company="카카오뱅크", account="net_income"))
        self.assertEqual(rec["readings"]["used"], "both")
        self.assertEqual(rec["answer"]["status"], "범위 밖")
        self.assertIn("카카오뱅크: 이 도구가 다루지 않는 회사라 답하지 않습니다", rec["answer"]["answer"])
        # a model that turns 카카오뱅크 into 카카오 disagrees with the rules instead of answering
        rec = self.turn("L11", reading(action="lookup", company="카카오", account="net_income"))
        self.assertEqual(rec["readings"]["used"], "neither (asked back)")
        self.assertEqual(rec["tool_call_count"], 0)

    def test_several_accounts(self):
        rec = self.turn("L12", reading(action="unsupported", company="카카오"))
        self.assertEqual((rec["readings"]["used"], rec["answer"]["status"]), ("both", "범위 밖"))
        self.assertIn("한 번에 계정 하나만 답합니다", rec["answer"]["answer"])

    def test_review_files_cover_lookup_questions(self):
        # the lookup baseline run of 2026-10-08 stopped at this step (finalize knew only dev_gold.json)
        import tempfile
        from finalize import write_review_files
        import run_eval
        cases, _ = run_eval.run("baseline", None, self.client, question_set="lookup", reference_date=REFERENCE)
        with tempfile.TemporaryDirectory() as folder:
            write_review_files(Path(folder), cases)
            sheet = (Path(folder) / "review_sheet.md").read_text(encoding="utf-8")
        self.assertIn("## L16", sheet)
        self.assertIn("범위 밖 / 회사 여러 개 (삼성전자, 카카오)", sheet)
        self.assertIn("되묻기 (삼성전자)", sheet)

    def test_every_rules_answer_has_only_grounded_numbers(self):
        from dart_review.crosscheck import ungrounded_in_answer
        for question in SPEC["questions"]:
            with self.subTest(question=question["id"]):
                rec = record()
                baseline_turn(question["question"], self.client, rec, REFERENCE)
                self.assertIsNotNone(rec["answer"], rec)
                self.assertEqual(ungrounded_in_answer(rec["answer"], rec["seen"], question["question"]), [])


if __name__ == "__main__":
    unittest.main()
