"""The evaluation runner with a scripted model (needs the cache; never needs the key or Ollama)."""

import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

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
        self.assertEqual(summary["automatic_passed"], {"correct": 13, "total": 13}, summary["failed"])
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
        self.assertEqual(summary["automatic_passed"], {"correct": 13, "total": 13}, summary["failed"])
        self.assertEqual(summary["model_attempts"], 13)

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
        self.assertTrue(record["score"]["automatic_passed"], record["score"]["problems"])
        self.assertEqual((record["model_attempts"], record["model_responses"], record["tool_call_count"]), (3, 3, 1))
        self.assertEqual((record["tool_args_first_ok"], record["tool_args_any_ok"]), (True, True))
        self.assertEqual(len(record["requests"]), 3)
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
        self.assertFalse(record["tool_args_first_ok"])
        self.assertEqual((record["score"]["basis_ok"], record["score"]["ungrounded"], record["score"]["automatic_passed"]), (False, [], False))

    def test_full_flow_budget_ends_without_a_final_request(self):
        chat = ScriptedChat(lambda messages, tools, schema: Reply("", [DEV01_CALL]))
        record = self.case("full", "dev01", chat)
        self.assertTrue(record["budget_exceeded"])
        self.assertEqual((record["model_attempts"], record["tool_call_count"]), (4, 3))
        self.assertTrue(all(call["tools"] for call in chat.calls))  # no final structured request was sent
        self.assertIsNone(record["answer"])
        self.assertEqual(record["score"]["format_error"], "budget exceeded (no final answer)")

    def test_a_batch_over_the_tool_budget_is_not_half_answered(self):
        # Codex 1-5 review E8: never send a conversation with a tool call left unanswered
        chat = ScriptedChat([Reply("", [DEV01_CALL] * 4)])
        record = self.case("full", "dev01", chat)
        self.assertTrue(record["budget_exceeded"])
        self.assertEqual((record["model_attempts"], record["tool_call_count"]), (1, 0))
        self.assertEqual(len(record["unexecuted_tool_calls"]), 4)

    def test_first_call_and_recovery_are_counted_apart(self):
        # Codex 1-5 review E7
        wrong = tool_call("compare_values", company="삼성전자", basis="별도", account="revenue",
                          current_period={"kind": "year_to_date", "year": 2025, "month": 12},
                          base_period={"kind": "year_to_date", "year": 2024, "month": 12})
        chat = ScriptedChat([Reply("", [wrong]), Reply("", [DEV01_CALL]), Reply("끝"), self.final_answer("dev01")])
        record = self.case("full", "dev01", chat)
        self.assertEqual((record["tool_args_first_ok"], record["tool_args_any_ok"]), (False, True))

    def test_arguments_given_as_a_json_string_are_compared(self):
        as_text = {"function": {"name": "compare_values", "arguments": json.dumps(DEV01_CALL["function"]["arguments"], ensure_ascii=False)}}
        chat = ScriptedChat([Reply("", [as_text]), Reply("끝"), self.final_answer("dev01")])
        self.assertTrue(self.case("full", "dev01", chat)["tool_args_first_ok"])

    def test_model_error_is_counted_as_an_attempt(self):
        # Codex 1-5 review E6
        def broken(messages, tools, schema):
            raise ModelError("connection refused")
        record = self.case("oracle", "dev01", ScriptedChat(broken))
        self.assertEqual((record["model_attempts"], record["model_responses"]), (1, 0))
        self.assertEqual(record["requests"][0]["error"], "connection refused")
        self.assertIn("model error", record["score"]["format_error"])

    def test_an_evaluator_bug_fails_one_question_and_is_reported(self):
        # Codex 1-5 review E1
        original = run_eval.score_case

        def flaky(gold, *args):
            if gold["id"] == "dev02":
                raise KeyError("boom")
            return original(gold, *args)

        with mock.patch.object(run_eval, "score_case", flaky):
            cases, summary = run_eval.run("rules", None, self.client, only=["dev01", "dev02", "dev03"])
        self.assertEqual(summary["evaluator_errors"], 1)
        self.assertEqual(summary["automatic_passed"], {"correct": 2, "total": 3})
        self.assertIn("KeyError", cases[1]["evaluator_error"])

    def test_unhashable_answer_field_is_a_format_error_not_a_crash(self):
        bad = json.loads(self.final_answer("dev01").content)
        bad["account"] = []
        record = self.case("oracle", "dev01", ScriptedChat([Reply(json.dumps(bad, ensure_ascii=False))]))
        self.assertIsNone(record["evaluator_error"])
        self.assertIn("unknown account", record["score"]["format_error"])

    def test_finished_questions_are_saved_as_the_run_goes(self):
        original = run_eval.run_case
        calls = []

        def interrupted(mode, question, *args, **kwargs):
            calls.append(question["id"])
            if len(calls) == 3:
                raise KeyboardInterrupt
            return original(mode, question, *args, **kwargs)

        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            with mock.patch.object(run_eval, "run_case", interrupted), self.assertRaises(KeyboardInterrupt):
                run_eval.main(["--mode", "rules", "--out", str(out)])
            lines = (out / "cases.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(line)["id"] for line in lines], ["dev01", "dev02"])
            self.assertTrue((out / "run.json").exists())

    def test_rules_run_writes_every_file(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "run"
            self.assertEqual(run_eval.main(["--mode", "rules", "--out", str(out)]), 0)
            self.assertEqual({path.name for path in out.iterdir()},
                             {"run.json", "cases.jsonl", "summary.json", "review_sheet.md", "human_review.json"})
            meta = json.loads((out / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(set(meta["contract"]), {"gold", "questions", "system_prompt", "final_instruction", "tools", "answer_schema",
                                                     "agent_prompt", "decision_instruction", "decision_schema", "paraphrases"})

    def test_full_flow_clarification_without_tools(self):
        ask = {"status": "되묻기", "company": "셀트리온", "account": None, "values": [], "change": None, "change_pct": None,
               "answer": "어떤 이익인지 알려 주세요.", "clarifying_question": "영업이익과 당기순이익 중 무엇을 비교할까요?"}
        chat = ScriptedChat([Reply("영업이익인지 당기순이익인지 확인이 필요합니다."), Reply(json.dumps(ask, ensure_ascii=False))])
        record = self.case("full", "dev12", chat)
        self.assertTrue(record["score"]["automatic_passed"], record["score"]["problems"])
        self.assertIsNone(record["tool_args_first_ok"])

    def test_bad_tool_calls_are_answered_with_errors(self):
        bad = tool_call("compare_values", company="NAVER")
        chat = ScriptedChat([Reply("", [bad]), Reply("끝"), self.final_answer("dev01")])
        record = self.case("full", "dev01", chat)
        self.assertIn("error", record["tool_calls"][0]["result"])
        self.assertFalse(record["tool_args_first_ok"])

    def test_odd_tool_call_shapes_do_not_crash_the_runner(self):
        # three per reply so every shape reaches the execution path (Codex 1-5 review 7.5)
        odd = [{"function": "compare_values"}, {"function": None}, 42]
        odder = [{}, {"function": {"name": ["compare_values"], "arguments": [1]}},
                 {"function": {"name": "compare_values", "arguments": {"company": [], "basis": [], "account": [],
                                                                       "current_period": {"kind": [], "year": 2025, "month": 12.0},
                                                                       "base_period": None}}}]
        for calls in (odd, odder):
            with self.subTest(calls=calls):
                chat = ScriptedChat([Reply("", calls), Reply("끝"), self.final_answer("dev01")])
                record = self.case("full", "dev01", chat)
                self.assertIsNone(record["evaluator_error"])
                self.assertEqual(record["tool_call_count"], 3)
                self.assertTrue(all("error" in call["result"] for call in record["tool_calls"]))
                self.assertFalse(record["tool_args_first_ok"])

    def test_a_model_error_fails_only_that_question(self):
        def broken(messages, tools, schema):
            raise ModelError("connection refused")
        cases, summary = run_eval.run("oracle", ScriptedChat(broken), self.client, only=["dev01", "dev02"])
        self.assertEqual(summary["automatic_passed"], {"correct": 0, "total": 2})
        self.assertTrue(all("model error" in case["score"]["format_error"] for case in cases))


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class SideBySideTests(unittest.TestCase):
    def test_no_difference_without_a_confirmed_common_currency(self):
        # Codex 1-5 review E9
        from dataclasses import replace
        from dart_review import tools
        client = DartClient(ResponseCache(run_eval.CACHE), key_loader=no_key, offline=True)
        arguments = {"company": "삼성전자", "account": "revenue", "period": {"kind": "year_to_date", "year": 2025, "month": 12}}
        self.assertEqual(tools.side_by_side(client, **arguments)["difference"], 95_562_929_000_000)
        original = tools.fact_from_response
        for currency in ("USD", None):
            with self.subTest(currency=currency):
                def changed(response, *args):
                    fact = original(response, *args)
                    return replace(fact, currency=currency) if fact.fs_div == "OFS" else fact
                with mock.patch.object(tools, "fact_from_response", changed):
                    result = tools.side_by_side(client, **arguments)
                self.assertEqual((result["status"], result["difference"]), ("확인 필요", None))
                self.assertIn("통화", result["reasons"][0])


class CommandLineTests(unittest.TestCase):
    def test_results_are_never_overwritten_and_model_flag_is_checked(self):
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "oracle", "--model", "x"])  # a model run must be recorded
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "rules", "--model", "x"])
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "oracle"])
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "rules", "--out", str(ROOT / "eval")])


if __name__ == "__main__":
    unittest.main()
