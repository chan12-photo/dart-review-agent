"""Design B: two independent readings, answer only when they agree, and the output number check (2-3)."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review import crosscheck  # noqa: E402
from dart_review.baseline import read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS  # noqa: E402
from dart_review.crosscheck import ReadingError, canonical, describe, model_to_reading, parse_model_reading  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402

QUESTIONS, GOLD = run_eval.load_questions("dev")
SPEC = {question["id"]: question for question in QUESTIONS}


def model_reading(question_id, **changes):
    """The structured reading a correct model would give for a development question."""
    expected = SPEC[question_id]["expected"]
    company = DEV_COMPANIES[expected["corp_code"]]
    if expected["action"] == "side_by_side":
        data = {"action": "side_by_side", "company": company, "basis": "연결", "account": expected["account"],
                "current_period": expected["period"], "base_period": expected["period"], "clarify_accounts": []}
    elif expected["action"] == "clarify":
        data = {"action": "clarify", "company": company, "basis": "연결", "account": "operating_income",
                "current_period": expected["current"], "base_period": expected["base"], "clarify_accounts": expected["options"]}
    else:
        data = {"action": "compare", "company": company, "basis": FS_DIVS[expected["fs_div"]], "account": expected["account"],
                "current_period": expected["current"], "base_period": expected["base"], "clarify_accounts": []}
    data.update(changes)
    return data


def reply(data):
    return Reply(json.dumps(data, ensure_ascii=False))


class ReadingTests(unittest.TestCase):
    def test_parse_model_reading(self):
        self.assertEqual(parse_model_reading(json.dumps(model_reading("dev01"), ensure_ascii=False))["action"], "compare")
        for bad in ("x", "{}", json.dumps({**model_reading("dev01"), "action": "answer"}),
                    json.dumps({**model_reading("dev01"), "clarify_accounts": ["profit"]})):
            with self.subTest(bad=bad):
                with self.assertRaises(ReadingError):
                    parse_model_reading(bad)

    def test_same_reading_from_rules_and_model(self):
        for question_id in ("dev01", "dev02", "dev05", "dev06", "dev12"):
            with self.subTest(question_id=question_id):
                rule = read(SPEC[question_id]["question"])
                model = model_to_reading(model_reading(question_id))
                self.assertEqual(canonical(rule.kind, rule.arguments, rule.company), canonical(model.kind, model.arguments, model.company))

    def test_a_different_base_period_is_a_different_reading(self):
        rule = read(SPEC["dev01"]["question"])
        model = model_to_reading(model_reading("dev01", base_period={"kind": "year_to_date", "year": 2023, "month": 12}))
        self.assertNotEqual(canonical(rule.kind, rule.arguments, rule.company), canonical(model.kind, model.arguments, model.company))

    def test_readings_are_described_relative_to_the_current_period(self):
        self.assertIn("전년 같은 기간과", describe(read(SPEC["dev01"]["question"])))
        self.assertIn("직전 분기와", describe(read(SPEC["dev06"]["question"])))
        self.assertIn("나란히", describe(read(SPEC["dev05"]["question"])))

    def test_unusable_company_is_no_reading(self):
        self.assertIsNone(canonical("compare", model_reading("dev01"), "NAVER"))


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class CrosscheckRunTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=lambda: (_ for _ in ()).throw(AssertionError()), offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def case(self, question_id, chat, question_text=None):
        question = copy.deepcopy(SPEC[question_id])
        if question_text:
            question["question"] = question_text
        return run_eval.run_case("crosscheck", question, GOLD[question_id], self.client, chat)

    def test_correct_readings_answer_every_question_with_one_request(self):
        def play(messages, tools, schema):
            question_id = next(key for key, value in SPEC.items() if value["question"] == messages[1]["content"])
            return reply(model_reading(question_id))

        cases, summary = run_eval.run("crosscheck", ScriptedChat(play), self.client)
        self.assertEqual(summary["automatic_passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual((summary["model_attempts"], summary["confident_wrong"], summary["ungrounded_numbers"]), (13, [], 0))
        self.assertTrue(all(case["readings"]["used"] == "both" for case in cases))

    def test_disagreement_asks_back_instead_of_answering(self):
        # the rules read "7~9월 … 4~6월보다" as a year-over-year comparison; a correct model reads the previous quarter
        record = self.case("dev06", ScriptedChat([reply(model_reading("dev06"))]), "카카오 2023년 7~9월 매출이 4~6월보다 얼마나 늘었어?")
        self.assertFalse(record["readings"]["agree"])
        self.assertEqual(record["answer"]["status"], "되묻기")
        self.assertIn("전년 같은 기간과", record["answer"]["clarifying_question"])
        self.assertIn("직전 분기와", record["answer"]["clarifying_question"])
        self.assertEqual(record["tool_call_count"], 0)
        summary = run_eval.summarize([record])
        self.assertEqual((summary["confident_wrong"], summary["asked_back_instead"]), ([], ["dev06"]))

    def test_one_reader_answers_with_a_visible_note(self):
        record = self.case("dev01", ScriptedChat([Reply("not json")]))
        self.assertEqual(record["readings"]["used"], "rule only")
        self.assertIn("규칙 해석 하나로만", record["answer"]["answer"])
        self.assertTrue(record["score"]["automatic_passed"])
        record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]), "삼성전자 매출, 작년과 올해를 비교해 줘")
        self.assertEqual(record["readings"]["used"], "model only")  # the rules find no year
        self.assertIn("모델 해석 하나로만", record["answer"]["answer"])

    def test_both_readings_fail(self):
        record = self.case("dev01", ScriptedChat([Reply("not json")]), "삼성전자 매출 알려줘")
        self.assertTrue(record["no_result"])
        self.assertFalse(record["score"]["automatic_passed"])

    def test_an_injected_number_is_withheld(self):
        # roadmap 2-3 completion criterion: an ungrounded number never reaches the output
        original = crosscheck.structured_answer

        def injected(result, explanation=None):
            answer = original(result, explanation)
            answer["answer"] += "\n영업이익률은 99.9%입니다."
            return answer

        with mock.patch.object(crosscheck, "structured_answer", injected):
            record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]))
        self.assertEqual(record["output_blocked"], ["99.9%"])
        self.assertIsNone(record["answer"])
        self.assertIn("output withheld", record["score"]["format_error"])

    def test_markdown_report_has_only_grounded_numbers(self):
        from dart_review.render import markdown_report
        from dart_review.crosscheck import ungrounded_in_answer
        for question_id in SPEC:
            with self.subTest(question_id=question_id):
                record = self.case(question_id, ScriptedChat([reply(model_reading(question_id))]))
                result = record["seen"][-1] if record["seen"] else None
                report = markdown_report(record["answer"], result)
                self.assertIn("**검증 상태:**", report)
                as_answer = {"answer": report, "clarifying_question": None}
                self.assertEqual(ungrounded_in_answer(as_answer, record["seen"], SPEC[question_id]["question"]), [])
        record = self.case("dev01", ScriptedChat([reply(model_reading("dev01"))]))
        report = markdown_report(record["answer"], record["seen"][-1])
        self.assertIn("| 비교 기간 | 연결 | 2025년 연간(1~12월) | 333,605,938,000,000 |", report)

    def test_confident_wrong_answers_are_counted(self):
        cases, summary = run_eval.run("baseline", None, self.client, question_set="paraphrase")
        self.assertEqual(summary["confident_wrong"], ["p06"])


if __name__ == "__main__":
    unittest.main()
