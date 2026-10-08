"""Replays the saved baseline and cross-check runs offline and requires the same answers.

The cross-check runs are replayed with the model replies recorded in their
cases.jsonl, so this needs neither Ollama nor the API key, only the
development cache. A code change that alters any of the 52 saved answers
fails here; an intended change must say so and be re-measured in a new run
folder (the saved runs are never rewritten).
"""

import json
from pathlib import Path
import unittest

from dart_review.baseline import baseline_turn
from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.crosscheck import crosscheck_turn
from dart_review.demo import answer as shown_answer
from dart_review.llm import Reply, ScriptedChat

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
RUNS = ROOT / "eval" / "feasibility_2026-10-07"


def no_key():
    raise AssertionError("replay must not need the API key")


def saved(folder):
    with (RUNS / folder / "cases.jsonl").open(encoding="utf-8") as lines:
        return [json.loads(line) for line in lines]


def new_record():
    return {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}


@unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class ReplayRegressionTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def test_baseline_runs(self):
        for folder in ("baseline_dev", "baseline_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    record = new_record()
                    baseline_turn(case["question"], self.client, record)
                    self.assertEqual(record["answer"], case["answer"])

    def test_crosscheck_runs_with_recorded_replies(self):
        for folder in ("crosscheck_dev", "crosscheck_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    chat = ScriptedChat([Reply(reply["content"]) for reply in case["replies"]])
                    record = new_record()
                    crosscheck_turn(case["question"], self.client, record, lambda messages, **kwargs: chat.chat(messages, **kwargs))
                    self.assertEqual(record["answer"], case["answer"])
                    self.assertEqual(record["readings"]["used"], case["readings"]["used"])

    def test_the_final_report_check_blocks_none_of_the_saved_answers(self):
        # review B6: the whole Markdown report is now checked; a false alarm would hide a correct answer
        for folder in ("crosscheck_dev", "crosscheck_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    chat = ScriptedChat([Reply(reply["content"]) for reply in case["replies"]])
                    shown = shown_answer(case["question"], self.client, chat)
                    self.assertIsNone(shown["withheld"])
                    self.assertEqual(shown["answer"], case["answer"])
                    self.assertIsNotNone(shown["report"])


if __name__ == "__main__":
    unittest.main()
