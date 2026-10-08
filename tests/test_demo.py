"""The replay demo runs from committed files only: no cache, no key, no model server, no network."""

import io
import json
from pathlib import Path
import sys
from contextlib import redirect_stdout
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from dart_review import crosscheck, demo  # noqa: E402
from dart_review.__main__ import main  # noqa: E402
from dart_review.crosscheck import READING_PROMPT_VERSION  # noqa: E402
from dart_review.demo import DEMO_QUESTIONS, ReplayMismatch, run_demo  # noqa: E402
from scoring import score_case  # noqa: E402

GOLD = {answer["question"]: answer for answer in json.loads((ROOT / "eval" / "dev_gold.json").read_text(encoding="utf-8"))["answers"]}
RECORDING = json.loads((ROOT / "demo" / "model_replies.json").read_text(encoding="utf-8"))
# The recorded readings belong to one reading prompt; after a prompt change they
# must be re-recorded with a real model run (scripts/build_demo_fixtures.py).
# Until then the replay refuses to run (test_a_stale_recording_is_refused) and
# the tests that replay it are skipped, saying why.
needs_current_recording = unittest.skipUnless(
    RECORDING.get("prompt_version") == READING_PROMPT_VERSION,
    f"demo/model_replies.json is for {RECORDING.get('prompt_version', 'reading-v1')}, not {READING_PROMPT_VERSION}")


class DemoTests(unittest.TestCase):
    @needs_current_recording
    def test_representative_requests_pass_the_scorer_offline(self):
        results, client = run_demo()
        self.assertEqual(client.network_requests, 0)
        self.assertEqual([item["answer"]["status"] for item in results], ["비교 가능", "비교 가능", "비교 가능", "나란히 표시", "데이터 없음"])
        for item in results:
            with self.subTest(question=item["question"]):
                self.assertEqual(item["readings"]["used"], "both")
                self.assertIsNone(item["withheld"])
                self.assertIn("**검증 상태:**", item["report"])
                score = score_case(GOLD[item["question"]], item["answer"], item["seen"], item["question"])
                self.assertTrue(score.automatic_passed, score.problems)

    def test_the_replay_stops_when_the_prompt_changes(self):
        with mock.patch.object(crosscheck, "READING_SYSTEM_PROMPT", crosscheck.READING_SYSTEM_PROMPT + " "):
            with self.assertRaises(ReplayMismatch):
                run_demo()

    def test_the_replay_stops_for_an_unrecorded_question(self):
        with mock.patch.object(demo, "DEMO_QUESTIONS", DEMO_QUESTIONS + ["카카오 2025년 매출은?"]):
            with self.assertRaises(ReplayMismatch):
                run_demo()

    @needs_current_recording
    def test_command_line(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["demo"]), 0)
        self.assertIn("OpenDART 네트워크 요청 0회", output.getvalue())
        self.assertEqual(output.getvalue().count("**검증 상태:**"), 5)

    def test_a_stale_recording_is_refused(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "model_replies.json").write_text(json.dumps({"prompt_version": "reading-v0", "replies": {}}), encoding="utf-8")
            with self.assertRaises(ReplayMismatch):
                run_demo(Path(folder))


class AskCommandTests(unittest.TestCase):
    """python -m dart_review ask, on the committed demo data (no cache, no key, no Ollama)."""

    def run_ask(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["ask", *args, "--cache", str(ROOT / "demo" / "opendart"), "--offline"])
        return code, output.getvalue()

    @needs_current_recording
    def test_cross_checked_answer_with_the_recorded_model_reading(self):
        from dart_review import __main__ as cli
        with mock.patch.object(cli, "OllamaChat", lambda model: demo.ReplayChat(RECORDING["replies"])):
            code, text = self.run_ask(DEMO_QUESTIONS[0], "--reference-date", RECORDING["reference_date"])
        self.assertEqual(code, 0)
        self.assertIn("**검증 상태:** 비교 가능", text)
        self.assertIn("해석 대조: both", text)

    def test_rules_only_is_marked(self):
        code, text = self.run_ask(DEMO_QUESTIONS[0], "--no-model")
        self.assertEqual(code, 0)
        self.assertIn("규칙 해석 하나로만 확인한 답", text)
        self.assertIn("해석 대조: rules only (--no-model)", text)

    def test_an_unreadable_model_reply_is_withheld_not_answered_by_the_rules(self):
        # policy 2026-10-08: without the model's reading the rules alone do not answer
        from dart_review import __main__ as cli
        from dart_review.llm import Reply, ScriptedChat
        with mock.patch.object(cli, "OllamaChat", lambda model: ScriptedChat([Reply("not json")])):
            code, text = self.run_ask(DEMO_QUESTIONS[0])
        self.assertEqual(code, 0)
        self.assertIn("모델 해석을 얻지 못해 답하지 않습니다", text)
        self.assertNotIn("**검증 상태:**", text)
        self.assertIn("해석 대조: rule only (withheld)", text)

    def test_unavailable_model_and_missing_data_are_reported(self):
        from dart_review import __main__ as cli
        from dart_review.llm import ModelError, ScriptedChat

        def refuse(messages, tools, schema):
            raise ModelError("could not reach the local Ollama server")
        with mock.patch.object(cli, "OllamaChat", lambda model: ScriptedChat(refuse)):
            code, text = self.run_ask(DEMO_QUESTIONS[0])
        self.assertEqual(code, 3)
        self.assertIn("--no-model", text)
        code, text = self.run_ask("카카오 2025년 매출", "--no-model")  # not in the demo data
        self.assertEqual(code, 0)
        self.assertIn("답할 수 있는 해석이나 조회 결과가 없음", text)

    def test_json_output(self):
        code, text = self.run_ask(DEMO_QUESTIONS[4], "--no-model", "--json")
        self.assertEqual(json.loads(text)["answer"]["status"], "데이터 없음")


if __name__ == "__main__":
    unittest.main()
