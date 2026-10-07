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
from dart_review.demo import DEMO_QUESTIONS, ReplayMismatch, run_demo  # noqa: E402
from scoring import score_case  # noqa: E402

GOLD = {answer["question"]: answer for answer in json.loads((ROOT / "eval" / "dev_gold.json").read_text(encoding="utf-8"))["answers"]}


class DemoTests(unittest.TestCase):
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

    def test_command_line(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["demo"]), 0)
        self.assertIn("OpenDART 네트워크 요청 0회", output.getvalue())
        self.assertEqual(output.getvalue().count("**검증 상태:**"), 5)


if __name__ == "__main__":
    unittest.main()
