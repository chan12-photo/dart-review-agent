"""The 2-1 agent: code-rendered facts, the model's decision, and the explanation check."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review.agent import DecisionError, check_explanation, company_in, parse_decision  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402
from dart_review.render import format_won, period_text  # noqa: E402

SPEC = {question["id"]: question for question in json.loads(run_eval.SPEC.read_text(encoding="utf-8"))["questions"]}
GOLD = {answer["id"]: answer for answer in json.loads(run_eval.GOLD.read_text(encoding="utf-8"))["answers"]}


def no_key():
    raise AssertionError("must not need the key")


def decision(action="answer", accounts=(), explanation=None):
    return Reply(json.dumps({"action": action, "clarify_accounts": list(accounts), "explanation": explanation}, ensure_ascii=False))


class RenderTests(unittest.TestCase):
    def test_amounts(self):
        cases = {333_605_938_000_000: "333조 6,059억 원", 5_000_000_000_000: "5조 원", 118_455_750_578: "1,184억 원",
                 -161_870_567_171: "-1,618억 원", 50_000_000: "5,000만 원", 999: "999원"}
        for amount, text in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(format_won(amount), text)

    def test_periods_name_their_kind(self):
        cases = [({"start": None, "end": "2025-09-30"}, "2025년 9월 30일 시점"),
                 ({"start": "2025-01-01", "end": "2025-12-31"}, "2025년 연간(1~12월)"),
                 ({"start": "2025-01-01", "end": "2025-06-30"}, "2025년 상반기(1~6월 누적)"),
                 ({"start": "2025-01-01", "end": "2025-03-31"}, "2025년 1분기(1~3월)"),
                 ({"start": "2025-01-01", "end": "2025-09-30"}, "2025년 1~9월 누적"),
                 ({"start": "2025-07-01", "end": "2025-09-30"}, "2025년 3분기(7~9월, 3개월)")]
        for period, text in cases:
            with self.subTest(period=period):
                self.assertEqual(period_text(period), text)


class DecisionTests(unittest.TestCase):
    def test_parse_decision(self):
        self.assertEqual(parse_decision('{"action": "clarify", "clarify_accounts": ["net_income"], "explanation": null}')["action"], "clarify")
        for bad in ("x", "{}", '{"action": "maybe", "clarify_accounts": [], "explanation": null}',
                    '{"action": "answer", "clarify_accounts": ["profit"], "explanation": null}',
                    '{"action": "answer", "clarify_accounts": [], "explanation": 3}',
                    '{"action": "answer", "clarify_accounts": [], "explanation": null, "extra": 1}'):
            with self.subTest(bad=bad):
                with self.assertRaises(DecisionError):
                    parse_decision(bad)

    def test_company_in_question(self):
        self.assertEqual(company_in("셀트리온 2025년 이익이 늘었어?"), "셀트리온")
        self.assertEqual(company_in("이익이 늘었어?"), "")

    def test_explanation_numbers_must_be_grounded(self):
        seen = [{"change_pct": "10.88", "current": {"amount": 333_605_938_000_000}}]
        self.assertEqual(check_explanation("메모리 가격 회복이 영향을 준 것으로 보인다(추정).", seen, "2025년"),
                         ("메모리 가격 회복이 영향을 준 것으로 보인다(추정).", None))
        kept, dropped = check_explanation("영업이익률은 12.3%다.", seen, "2025년")
        self.assertIsNone(kept)
        self.assertIn("12.3%", dropped)
        self.assertEqual(check_explanation("10.88% 늘어 두 자릿수 성장이다.", seen, "")[0], "10.88% 늘어 두 자릿수 성장이다.")
        self.assertIn("longer", check_explanation("가" * 301, seen, "")[1])
        self.assertEqual(check_explanation(None, seen, ""), (None, None))


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class AgentRunTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def case(self, question_id, chat):
        return run_eval.run_case("agent", SPEC[question_id], GOLD[question_id], self.client, chat)

    @staticmethod
    def tool_reply(name, arguments):
        return Reply("", [{"function": {"name": name, "arguments": arguments}}])

    def correct_script(self, question_id):
        question = SPEC[question_id]
        if question["expected"]["action"] == "clarify":
            return [Reply("어떤 이익인지 확인이 필요하다."), decision("clarify", question["expected"]["options"])]
        name, arguments = run_eval.interpretation_calls(question)[0]
        return [self.tool_reply(name, arguments), Reply("확인했다."), decision()]

    def test_a_correct_model_passes_every_question(self):
        scripts = {question_id: iter(self.correct_script(question_id)) for question_id in SPEC}

        def play(messages, tools, schema):
            question = messages[1]["content"]
            question_id = next(key for key, value in SPEC.items() if value["question"] == question)
            return next(scripts[question_id])

        cases, summary = run_eval.run("agent", ScriptedChat(play), self.client)
        self.assertEqual(summary["automatic_passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual(summary["tool_args_first_ok"], {"correct": 12, "total": 12})
        self.assertEqual(summary["ungrounded_numbers"], 0)

    def test_answer_text_states_company_basis_and_period_kind(self):
        record = self.case("dev04", ScriptedChat(self.correct_script("dev04")))
        text = record["answer"]["answer"]
        for phrase in ("셀트리온", "연결 기준", "1~9월 누적", "증가"):
            self.assertIn(phrase, text)

    def test_ungrounded_explanation_is_dropped_not_shown(self):
        script = self.correct_script("dev01")
        script[-1] = decision(explanation="영업이익률로 보면 12.3% 수준이다.")
        record = self.case("dev01", ScriptedChat(script))
        self.assertIn("12.3%", record["explanation_dropped"])
        self.assertNotIn("12.3%", record["answer"]["answer"])
        self.assertTrue(record["score"]["automatic_passed"])

    def test_grounded_explanation_is_shown_as_the_models(self):
        script = self.correct_script("dev01")
        script[-1] = decision(explanation="두 자릿수(10.88%) 성장이다.")
        record = self.case("dev01", ScriptedChat(script))
        self.assertIn("해석(모델): 두 자릿수(10.88%) 성장이다.", record["answer"]["answer"])

    def test_clarification_without_tools_names_the_company(self):
        record = self.case("dev12", ScriptedChat(self.correct_script("dev12")))
        self.assertEqual(record["answer"]["company"], "셀트리온")
        self.assertTrue(record["score"]["automatic_passed"], record["score"]["problems"])

    def test_decision_errors_and_missing_results_fail_cleanly(self):
        script = self.correct_script("dev01")
        script[-1] = Reply("not json")
        record = self.case("dev01", ScriptedChat(script))
        self.assertIn("decision format error", record["score"]["format_error"])
        self.assertIsNone(record["evaluator_error"])
        record = self.case("dev01", ScriptedChat([Reply("모르겠다."), decision()]))
        self.assertTrue(record["no_result"])
        self.assertEqual(record["score"]["format_error"], "no successful tool result to answer from")

    def test_budget_ends_without_a_decision_request(self):
        name, arguments = run_eval.interpretation_calls(SPEC["dev01"])[0]
        chat = ScriptedChat(lambda messages, tools, schema: self.tool_reply(name, arguments))
        record = self.case("dev01", chat)
        self.assertTrue(record["budget_exceeded"])
        self.assertTrue(all(call["tools"] for call in chat.calls))
        self.assertIsNone(record["decision"])


if __name__ == "__main__":
    unittest.main()
