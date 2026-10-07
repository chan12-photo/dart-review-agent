"""The evaluation runner with a scripted model (needs the cache; never needs the key or Ollama)."""

import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import run_eval  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.llm import ModelError, Reply, ScriptedChat  # noqa: E402

SPEC = {question["id"]: question for question in json.loads(run_eval.SPEC.read_text(encoding="utf-8"))["questions"]}
GOLD = {answer["id"]: answer for answer in json.loads(run_eval.GOLD.read_text(encoding="utf-8"))["answers"]}


def no_key():
    raise AssertionError("must not need the key")


def tool_call(name, **arguments):
    return {"function": {"name": name, "arguments": arguments}}


DEV01_CALL = tool_call("compare_values", company="삼성전자", basis="연결", account="revenue",
                       current_period={"kind": "year_to_date", "year": 2025, "month": 12},
                       base_period={"kind": "year_to_date", "year": 2024, "month": 12})


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def case(self, mode, question_id, chat=None):
        return run_eval.run_case(mode, SPEC[question_id], GOLD[question_id], self.client, chat)

    def test_rules_mode_passes_every_question(self):
        cases, summary = run_eval.run("rules", None, self.client)
        self.assertEqual(summary["passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual(summary["ungrounded_numbers"], 0)

    def test_oracle_mode_with_a_faithful_model(self):
        def faithful(messages, tools, schema):
            self.assertIsNotNone(schema)
            self.assertIsNone(tools)
            text = messages[-1]["content"]
            question = next(q for q in SPEC.values() if f"질문: {q['question']}" in text)
            results = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", text, re.S)]
            return Reply(json.dumps(run_eval.rules_answer(question, results), ensure_ascii=False))

        chat = ScriptedChat(faithful)
        cases, summary = run_eval.run("oracle", chat, self.client)
        self.assertEqual(summary["passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual(summary["model_requests"], 13)

    def test_oracle_gives_both_candidates_for_the_ambiguous_question(self):
        chat = ScriptedChat([Reply("{}")])
        record = self.case("oracle", "dev12", chat)
        self.assertEqual([result["account"] for result in record["seen"]], ["operating_income", "net_income"])
        self.assertTrue(record["score"]["format_error"])

    def final_answer(self, question_id):
        results = [run_eval.execute_tool(self.client, name, arguments) for name, arguments in run_eval.interpretation_calls(SPEC[question_id])]
        return Reply(json.dumps(run_eval.rules_answer(SPEC[question_id], results), ensure_ascii=False))

    def test_full_flow_success(self):
        chat = ScriptedChat([Reply("", [DEV01_CALL]), Reply("결과를 확인했습니다."), self.final_answer("dev01")])
        record = self.case("full", "dev01", chat)
        self.assertTrue(record["score"]["passed"], record["score"]["problems"])
        self.assertEqual((record["model_requests"], record["tool_call_count"], record["tool_args_ok"]), (3, 1, True))
        self.assertEqual(chat.calls[-1]["schema"], True)
        self.assertEqual([call["tools"] for call in chat.calls], [True, True, False])

    def test_full_flow_with_the_wrong_basis(self):
        wrong = tool_call("compare_values", company="삼성전자", basis="별도", account="revenue",
                          current_period={"kind": "year_to_date", "year": 2025, "month": 12},
                          base_period={"kind": "year_to_date", "year": 2024, "month": 12})
        result = run_eval.execute_tool(self.client, "compare_values", wrong["function"]["arguments"])
        answer = {"status": "비교 가능", "company": "삼성전자", "account": "revenue",
                  "values": [{"basis": "별도", "start": "2025-01-01", "end": "2025-12-31", "amount": result["current"]["amount"]},
                             {"basis": "별도", "start": "2024-01-01", "end": "2024-12-31", "amount": result["base"]["amount"]}],
                  "change": result["change"], "change_pct": result["change_pct"], "clarifying_question": None,
                  "answer": f"별도 기준 매출은 {result['current']['amount']:,}원으로 {result['change_pct']}% 변했습니다."}
        chat = ScriptedChat([Reply("", [wrong]), Reply("끝"), Reply(json.dumps(answer, ensure_ascii=False))])
        record = self.case("full", "dev01", chat)
        self.assertFalse(record["tool_args_ok"])
        self.assertEqual((record["score"]["basis_ok"], record["score"]["ungrounded"], record["score"]["passed"]), (False, [], False))

    def test_full_flow_budget(self):
        chat = ScriptedChat(lambda messages, tools, schema: self.final_answer("dev01") if schema else Reply("", [DEV01_CALL]))
        record = self.case("full", "dev01", chat)
        self.assertTrue(record["budget_exceeded"])
        self.assertFalse(record["score"]["passed"])
        self.assertEqual(record["tool_call_count"], 3)
        self.assertEqual(record["model_requests"], run_eval.MAX_MODEL_CALLS)

    def test_full_flow_clarification_without_tools(self):
        ask = {"status": "되묻기", "company": "셀트리온", "account": None, "values": [], "change": None, "change_pct": None,
               "answer": "어떤 이익인지 알려 주세요.", "clarifying_question": "영업이익과 당기순이익 중 무엇을 비교할까요?"}
        chat = ScriptedChat([Reply("영업이익인지 당기순이익인지 확인이 필요합니다."), Reply(json.dumps(ask, ensure_ascii=False))])
        record = self.case("full", "dev12", chat)
        self.assertTrue(record["score"]["passed"], record["score"]["problems"])
        self.assertIsNone(record["tool_args_ok"])

    def test_bad_tool_calls_are_answered_with_errors(self):
        bad = tool_call("compare_values", company="NAVER")
        chat = ScriptedChat([Reply("", [bad]), Reply("끝"), self.final_answer("dev01")])
        record = self.case("full", "dev01", chat)
        self.assertIn("error", record["tool_calls"][0]["result"])
        self.assertFalse(record["tool_args_ok"])

    def test_a_model_error_fails_only_that_question(self):
        def broken(messages, tools, schema):
            raise ModelError("connection refused")
        cases, summary = run_eval.run("oracle", ScriptedChat(broken), self.client, only=["dev01", "dev02"])
        self.assertEqual(summary["passed"], {"correct": 0, "total": 2})
        self.assertTrue(all("model error" in case["score"]["format_error"] for case in cases))


class CommandLineTests(unittest.TestCase):
    def test_results_are_never_overwritten_and_model_flag_is_checked(self):
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "rules", "--model", "x"])
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "oracle"])
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "rules", "--out", str(ROOT / "eval")])


if __name__ == "__main__":
    unittest.main()
