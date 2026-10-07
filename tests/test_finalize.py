"""Human review and the final score (no cache needed)."""

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


class FinalScoreTests(unittest.TestCase):
    def test_final_pass_needs_both_the_automatic_score_and_the_text_review(self):
        cases = [case("dev01", True), case("dev02", True), case("dev03", False, ungrounded=["1.5%"])]
        review = {"cases": {"dev01": {"body_ok": True}, "dev02": {"body_ok": False, "note": "2번: 기간"},
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
        review = {"cases": {item["id"]: {"body_ok": index < 11} for index, item in enumerate(cases)}}
        result = final_scores(cases, review, "oracle")
        self.assertEqual(result["threshold"], {"needed": 11, "met": True})
        review["cases"]["dev11"]["body_ok"] = False
        self.assertFalse(final_scores(cases, review, "oracle")["threshold"]["met"])

    def test_review_files(self):
        cases = [case("dev01", True)]
        self.assertIn("## dev01", review_sheet(cases))
        self.assertEqual(review_template(cases)["cases"]["dev01"]["body_ok"], None)


if __name__ == "__main__":
    unittest.main()
