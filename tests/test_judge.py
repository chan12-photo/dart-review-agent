"""The 3-1 judge (eval/judge.py): outcome cells, run checks, and the criteria, on synthetic records."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import judge  # noqa: E402
import run_eval  # noqa: E402

LOOKUP_RUN = ROOT / "eval" / "lookup_2026-10-08" / "baseline_lookup"
GOLD = {gold["decision"]: gold for gold in run_eval.load_questions("lookup")[1].values()}


def case(status, passed=True, format_error=None):
    return {"id": "X", "answer": None if status is None else {"status": status},
            "score": {"automatic_passed": passed, "format_error": format_error, "ungrounded": []}}


class OutcomeTests(unittest.TestCase):
    def test_cells(self):
        cases = [(("값 확인", True), "answer", "정답 제공"), (("값 확인", False), "answer", "잘못된 수치 답"),
                 (("비교 가능", True), "refuse", "정답 제공"), (("값 확인", False), "clarify", "잘못된 수치 답"),
                 (("범위 밖", True), "refuse", "맞는 거절"), (("범위 밖", False), "refuse", "잘못된 거절"),
                 (("데이터 없음", False), "answer", "잘못된 거절"), (("되묻기", True), "clarify", "맞는 되묻기"),
                 (("되묻기", False), "clarify", "잘못된 되묻기"), (("되묻기", False), "answer", "불필요한 되묻기"),
                 ((None, False), "answer", "보류·무응답"), (("이상한 상태", False), "refuse", "잘못된 수치 답")]
        for (status, passed), decision, expected in cases:
            with self.subTest(status=status, decision=decision):
                self.assertEqual(judge.outcome(case(status, passed), {"decision": decision}, passed), expected)
        # an answer the scorer could not read counts as nothing shown
        self.assertEqual(judge.outcome(case("값 확인", False, "not JSON"), {"decision": "answer"}, False), "보류·무응답")


@unittest.skipUnless(LOOKUP_RUN.exists(), "needs the committed lookup baseline run")
class JudgeTests(unittest.TestCase):
    def setUp(self):
        meta, cases = judge.load_run(LOOKUP_RUN)
        meta = {**meta, "git": {"commit": "c0ffee", "dirty": False}}
        questions = {question["id"]: question for question in run_eval.load_questions("lookup")[0]}
        for item in cases:  # both readers right, as if from a cross-check run
            key = judge.expected_key(questions[item["id"]])
            item["readings"] = {"used": "both", "rule_key": list(key), "model_key": list(key)}
        self.meta, self.cases = meta, cases

    def runs(self, crosscheck=None, baseline=None, **meta_changes):
        return {"crosscheck": ({**self.meta, **meta_changes}, crosscheck or copy.deepcopy(self.cases)),
                "baseline": (self.meta, baseline or copy.deepcopy(self.cases))}

    def test_all_right_meets_the_criteria(self):
        report = judge.judge(self.runs())
        self.assertEqual(report["problems"], [])
        self.assertEqual(report["verdict"], "기준 충족")
        self.assertEqual(report["checks"]["해결률 ≥ 70%"]["value"], 1.0)
        self.assertEqual(list(report["interpretation"]), ["규칙 정답 / 모델 정답"])
        self.assertIsNone(report["checks"]["범위 밖·모호 ≥ 75%"]["met"])  # no bundle C in this set

    def test_one_wrong_answer_fails_and_an_averted_one_is_counted(self):
        crosscheck = copy.deepcopy(self.cases)
        wrong = next(item for item in crosscheck if item["id"] == "L01")
        wrong["score"]["automatic_passed"] = False
        baseline = copy.deepcopy(self.cases)
        baseline_wrong = next(item for item in baseline if item["id"] == "L02")
        baseline_wrong["score"]["automatic_passed"] = False
        report = judge.judge(self.runs(crosscheck, baseline))
        self.assertEqual(report["verdict"], "기준 미달")
        self.assertEqual(report["outcome_table"]["crosscheck"]["잘못된 수치 답"], ["L01"])
        self.assertEqual(report["crosscheck_effect"]["막은 오답"], ["L02"])
        self.assertEqual(report["crosscheck_effect"]["일치한 오답"], ["L01"])

    def test_run_problems_suspend_the_verdict(self):
        duplicated = copy.deepcopy(self.cases) + [copy.deepcopy(self.cases[0])]
        for runs, expected in ((self.runs(duplicated), "duplicates ['L01']"),
                               (self.runs(self.cases[1:]), "missing ['L01']"),
                               (self.runs(reference_date="2027-01-01"), "reference_date differs"),
                               (self.runs(git={"commit": "other", "dirty": False}), "different code"),
                               (self.runs(git={"commit": "c0ffee", "dirty": True}), "dirty tree")):
            with self.subTest(expected=expected):
                report = judge.judge(runs)
                self.assertEqual(report["verdict"], "판정 보류")
                self.assertTrue(any(expected in problem for problem in report["problems"]), report["problems"])
                self.assertNotIn("checks", report)

    def test_a_human_review_result_replaces_the_automatic_pass(self):
        final = {"confirmed_by_user": False, "per_case": [{"id": "L03", "reviewed_passed": False}]}
        report = judge.judge(self.runs(), {"crosscheck": final})
        self.assertEqual(report["outcomes"]["crosscheck"]["L03"], "잘못된 수치 답")
        self.assertEqual(report["review"]["crosscheck"], {"confirmed_by_user": False})


class EvaluationRunGuardTests(unittest.TestCase):
    def test_an_evaluation_set_run_needs_a_recorded_clean_run(self):
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "baseline", "--companies", "sealed-3-1"])  # no --out
        with self.assertRaises(SystemExit):
            run_eval.main(["--mode", "baseline", "--companies", "sealed-3-1", "--out", "/nonexistent/x", "--allow-dirty"])


if __name__ == "__main__":
    unittest.main()


class RescorePathTests(unittest.TestCase):
    """Codex 3.1: the rescore uses the runner's scoring function and the run's own question set."""

    def test_the_saved_1_5_rescore_is_reproduced_and_later_runs_are_unchanged(self):
        import rescore
        base = ROOT / "eval" / "feasibility_2026-10-07"
        for folder in ("oracle", "full"):
            with self.subTest(folder=folder):
                gold = rescore.golds_for(base / folder)
                saved = {json.loads(line)["id"]: json.loads(line)["score"]
                         for line in (base / folder / "cases_rescored_6b67c4f.jsonl").read_text(encoding="utf-8").splitlines()}
                for line in (base / folder / "cases.jsonl").read_text(encoding="utf-8").splitlines():
                    case = json.loads(line)
                    self.assertEqual(rescore.rescore_case(case, gold[case["id"]])["score"], saved[case["id"]])
        for folder in (base / "crosscheck_paraphrase", ROOT / "eval" / "reading-v4_2026-10-08" / "crosscheck_lookup"):
            with self.subTest(folder=folder.name):
                gold = rescore.golds_for(folder)  # paraphrase (p..) and lookup (L..) ids, not only dev_gold.json
                for line in (folder / "cases.jsonl").read_text(encoding="utf-8").splitlines():
                    case = json.loads(line)
                    self.assertEqual(rescore.rescore_case(case, gold[case["id"]])["score"], case["score"])
