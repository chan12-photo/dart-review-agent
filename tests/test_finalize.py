"""Human review and the final score (no cache needed)."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from finalize import ReviewError, final_scores, review_sheet, review_template  # noqa: E402


def case(case_id, automatic, **score):
    base = {"id": case_id, "format_error": None, "status_ok": True, "decision_ok": True, "numbers_ok": True,
            "basis_ok": True, "refusal_ok": None, "wording_ok": None, "ungrounded": [], "unparsed": [],
            "warnings": [], "problems": [], "automatic_passed": automatic}
    base.update(score)
    return {"id": case_id, "question": "질문", "answer": '{"status": "비교 가능", "answer": "답"}', "score": base}



def quiet(function, *args):
    """Run a command-line main without its JSON summary on the test output."""
    with redirect_stdout(io.StringIO()):
        return function(*args)


class FinalScoreTests(unittest.TestCase):
    def test_final_pass_needs_both_the_automatic_score_and_the_text_review(self):
        cases = [case("dev01", True), case("dev02", True), case("dev03", False, ungrounded=["1.5%"])]
        review = {"cases": {"dev01": {"body_ok": True}, "dev02": {"body_ok": False, "failure_kind": "수치", "note": "2번: 기간"},
                            "dev03": {"body_ok": True}}}
        result = final_scores(cases, review, "full")
        self.assertEqual((result["automatic_passed"], result["reviewed_passed"]), (2, 1))

    def test_only_unparsed_notations_can_be_accepted(self):
        cases = [case("dev01", False, ungrounded=["1천2백억 원"], unparsed=["1천"])]
        with self.assertRaises(ReviewError):
            final_scores(cases, {"cases": {"dev01": {"body_ok": True, "accepted_unparsed": ["1천2백억 원"]}}}, "oracle")
        cases = [case("dev01", False, ungrounded=["1천"], unparsed=["1천"])]
        result = final_scores(cases, {"cases": {"dev01": {"body_ok": True, "accepted_unparsed": ["1천"]}}}, "oracle")
        self.assertEqual(result["reviewed_passed"], 1)
        # a structural failure is never rescued by accepting a notation
        cases = [case("dev01", False, ungrounded=["1천"], unparsed=["1천"], status_ok=False)]
        result = final_scores(cases, {"cases": {"dev01": {"body_ok": True, "accepted_unparsed": ["1천"]}}}, "oracle")
        self.assertEqual(result["reviewed_passed"], 0)

    def test_every_question_must_be_reviewed(self):
        with self.assertRaises(ReviewError):
            final_scores([case("dev01", True)], {"cases": {"dev01": {"body_ok": None}}}, "oracle")

    def test_oracle_threshold_is_eleven_of_thirteen(self):
        cases = [case(f"dev{index:02d}", True) for index in range(1, 14)]
        review = {"cases": {item["id"]: {"body_ok": index < 11, "failure_kind": None if index < 11 else "설명"}
                            for index, item in enumerate(cases)}}
        result = final_scores(cases, review, "oracle")
        self.assertEqual(result["threshold"], {"needed": 11, "met": True})
        review["cases"]["dev11"].update(body_ok=False, failure_kind="수치")
        self.assertFalse(final_scores(cases, review, "oracle")["threshold"]["met"])

    def test_review_files(self):
        cases = [case("dev01", True)]
        self.assertIn("## dev01", review_sheet(cases))
        self.assertEqual(review_template(cases)["cases"]["dev01"]["body_ok"], None)


if __name__ == "__main__":
    unittest.main()



class SecondReviewFinalizeTests(unittest.TestCase):
    """Codex 3-1 second review 1, 3, 5."""

    def test_a_failed_text_must_say_what_failed(self):
        with self.assertRaises(ReviewError):
            final_scores([case("dev01", True)], {"cases": {"dev01": {"body_ok": False}}}, "oracle")
        result = final_scores([case("dev01", True)], {"cases": {"dev01": {"body_ok": False, "failure_kind": "설명"}}}, "oracle")
        self.assertEqual(result["per_case"][0]["failure_kind"], "설명")

    def test_the_sealed_review_sheet_uses_the_run_gold(self):
        # ids only: no sealed question is run here (that would show results before pre-registration)
        import run_eval
        from dart_review.companies import using_company_set
        from finalize import review_sheet
        with using_company_set("sealed-3-1"):
            questions, golds = run_eval.load_questions("file:eval/sealed_3-1/questions.json")
        cases = [{"id": question["id"], "question": question["question"], "answer": None,
                  "score": {"automatic_passed": False, "format_error": "no answer"}} for question in questions]
        sheet = review_sheet(cases, golds)
        self.assertEqual(sheet.count("\n## "), 36)
        self.assertIn("## U14", sheet)
        with self.assertRaises(KeyError):  # the development gold alone does not know the sealed ids
            review_sheet(cases)

    def test_finalize_records_the_run_and_never_overwrites(self):
        import tempfile
        from finalize import main
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "run.json").write_text(json.dumps({"mode": "crosscheck"}), encoding="utf-8")
            (folder / "cases.jsonl").write_text(json.dumps(case("dev01", True)) + "\n", encoding="utf-8")
            (folder / "human_review.json").write_text(json.dumps({"cases": {"dev01": {"body_ok": True}}}), encoding="utf-8")
            self.assertEqual(quiet(main, [str(folder)]), 0)
            first = json.loads((folder / "final.json").read_text(encoding="utf-8"))
            self.assertEqual(first["mode"], "crosscheck")
            self.assertEqual(len(first["cases_sha256"]), 64)
            self.assertEqual(quiet(main, [str(folder)]), 2)  # a second review needs a reason
            (folder / "human_review.json").write_text(json.dumps({"revision_reason": "사용자 확인", "cases": {"dev01": {"body_ok": True}}}),
                                                     encoding="utf-8")
            self.assertEqual(quiet(main, [str(folder)]), 0)
            self.assertTrue((folder / "final_v2.json").exists())
            self.assertEqual(json.loads((folder / "final.json").read_text(encoding="utf-8")), first)
