"""Replays the saved baseline and cross-check runs offline and requires the same answers.

The cross-check runs are replayed with the model replies recorded in their
cases.jsonl, so this needs neither Ollama nor the API key, only the
development cache. A code change that alters any of the 52 saved answers
fails here; an intended change must say so and be re-measured in a new run
folder (the saved runs are never rewritten).
"""

import difflib
import json
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from dart_review.baseline import baseline_turn
from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.crosscheck import crosscheck_turn
from dart_review.demo import answer as shown_answer
from dart_review.llm import Reply, ScriptedChat
from dart_review.render import polite

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache"
RUNS = ROOT / "eval" / "feasibility_2026-10-07"


# Answers a later rule change was meant to change. Each must now pass the scorer against its gold, so an
# intended change cannot hide a regression. p06 ("7~9월 매출이 4~6월보다"): the rules read two named periods
# since the Codex 3-1 first review (finding 7), so the baseline no longer misreads it and the cross-check no
# longer has to ask back.
INTENDED_CHANGES = {("baseline_paraphrase", "p06"), ("crosscheck_paraphrase", "p06")}


# v0.1.x wording (after the 3-1 evaluation): tool notes and reasons are shown in the polite style, and the
# account clarifying question no longer assumes a comparison. Only these word-level changes are allowed;
# statuses, values, and every other word must stay exactly as saved.
OLD_CLARIFY = (("중 어느 것을 비교할까요?", "중 어느 것을 말씀하신 건가요?"),
               ("을 비교할지 알려 주세요.", "을 말씀하신 건지 알려 주세요."))


def politely_reworded(old: str, new: str) -> bool:
    for before, after in OLD_CLARIFY:
        old = old.replace(before, after)
    old_words, new_words = re.split(r"(\s+)", old), re.split(r"(\s+)", new)  # spaces and line breaks kept as tokens
    matcher = difflib.SequenceMatcher(a=old_words, b=new_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "replace" or i2 - i1 != j2 - j1:
            return False
        for before, after in zip(old_words[i1:i2], new_words[j1:j2]):
            core = before.rstrip(".)\n")
            tail = before[len(core):]
            if after != polite(core) + tail or after == before:
                return False
    return True


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

    def assert_same_or_intended(self, folder, case, record):
        if (folder, case["id"]) not in INTENDED_CHANGES:
            new, old = dict(record["answer"]), dict(case["answer"])
            for field in ("answer", "clarifying_question"):
                if new.get(field) != old.get(field) and politely_reworded(old.get(field) or "", new.get(field) or ""):
                    new[field] = old[field]
            self.assertEqual(new, old)
            return
        import run_eval
        from scoring import score_case
        self.assertNotEqual(record["answer"], case["answer"], "an intended change that no longer changes anything")
        gold = run_eval.load_questions("paraphrase")[1][case["id"]]
        score = score_case(gold, record["answer"], record["seen"], case["question"])
        self.assertTrue(score.automatic_passed, score.problems)

    def test_baseline_runs(self):
        for folder in ("baseline_dev", "baseline_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    record = new_record()
                    baseline_turn(case["question"], self.client, record)
                    self.assert_same_or_intended(folder, case, record)

    def test_crosscheck_runs_with_recorded_replies(self):
        for folder in ("crosscheck_dev", "crosscheck_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    chat = ScriptedChat([Reply(reply["content"]) for reply in case["replies"]])
                    record = new_record()
                    crosscheck_turn(case["question"], self.client, record, lambda messages, **kwargs: chat.chat(messages, **kwargs))
                    self.assert_same_or_intended(folder, case, record)
                    if (folder, case["id"]) not in INTENDED_CHANGES:
                        self.assertEqual(record["readings"]["used"], case["readings"]["used"])

    def test_the_final_report_check_blocks_none_of_the_saved_answers(self):
        # review B6: the whole Markdown report is now checked; a false alarm would hide a correct answer
        for folder in ("crosscheck_dev", "crosscheck_paraphrase"):
            for case in saved(folder):
                with self.subTest(folder=folder, id=case["id"]):
                    chat = ScriptedChat([Reply(reply["content"]) for reply in case["replies"]])
                    shown = shown_answer(case["question"], self.client, chat)
                    self.assertIsNone(shown["withheld"])
                    self.assert_same_or_intended(folder, case, shown)
                    self.assertIsNotNone(shown["report"])


if __name__ == "__main__":
    unittest.main()
