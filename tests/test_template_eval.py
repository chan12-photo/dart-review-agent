"""The 3-5 template evaluation tooling (docs/EVAL_CONTRACT_3-5.ko.md).

The generated questions are checked against their expectations from the text alone (no product code), the
gold-side row rule on synthetic responses, the sampled human review, and the judge's 3-5 checks. Nothing here
runs the product on the template questions: that happens only after pre-registration (contract section 1).
"""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import build_template_gold as gold_rules  # noqa: E402
import build_template_questions as generator  # noqa: E402
import finalize  # noqa: E402
import judge  # noqa: E402
import run_eval  # noqa: E402
from build_gold import GoldError  # noqa: E402
from dart_review.accounts import ACCOUNTS  # noqa: E402
from dart_review.companies import SEALED_EVAL_COMPANIES  # noqa: E402

QUESTION_FILE = ROOT / "eval" / "template_3-5" / "questions.json"
SPEC = json.loads(QUESTION_FILE.read_text(encoding="utf-8"))
QUESTIONS = SPEC["questions"]


class CompositionTests(unittest.TestCase):
    def test_the_counts_are_the_contracts(self):
        self.assertEqual({family: count for family, (count, _) in generator.FAMILIES.items()}, judge.COMPOSITION_3_5)
        self.assertEqual(sum(judge.COMPOSITION_3_5.values()), 600)
        self.assertEqual(sum(count for family, count in judge.COMPOSITION_3_5.items() if family.startswith("A")), 480)
        found = {}
        for question in QUESTIONS:
            found[question["bundle"]] = found.get(question["bundle"], 0) + 1
        self.assertEqual(found, judge.COMPOSITION_3_5)
        self.assertEqual(len({question["id"] for question in QUESTIONS}), 600)

    def test_the_file_names_its_contract_freeze_policy_and_seed(self):
        self.assertEqual((SPEC["contract"], SPEC["freeze"], SPEC["seed"], SPEC["reference_date"]),
                         ("3-5", "eval/freeze_3-5.json", 20261009, "2026-10-08"))
        self.assertEqual(run_eval.freeze_file("file:eval/template_3-5/questions.json"), ROOT / "eval" / "freeze_3-5.json")
        self.assertEqual(run_eval.freeze_file("file:eval/sealed_3-1/questions.json"), ROOT / "eval" / "freeze_3-1.json")
        self.assertEqual(judge.contract_of("file:eval/sealed_3-1/questions.json"), "3-1")
        self.assertEqual(judge.contract_of("file:eval/template_3-5/questions.json"), "3-5")
        self.assertEqual(run_eval.review_policy("file:eval/template_3-5/questions.json"),
                         {"seed": 3505, "sample": {"crosscheck": 40, "baseline": 20}})


class WordingMatchesTheExpectationTests(unittest.TestCase):
    """Each question says the period, basis, company, and account its gold answer is for (read from the text)."""

    def year_words(self, year, question):
        words = [f"{year}년"]
        if question["template"].get("relative_year"):
            words += {2024: ["재작년"], 2025: ["작년"], 2026: ["올해"]}.get(year, [])
        return words

    def assert_period(self, text, period, question):
        self.assertTrue(any(word in text for word in self.year_words(period["year"], question)), (text, period))
        kind, month = period["kind"], period["month"]
        if kind == "quarter":
            self.assertIn(f"{month // 3}분기", text)
            self.assertNotIn("누적", text)
            self.assertNotIn("분기말", text)
        elif kind == "instant":
            self.assertIn(f"{month // 3}분기말" if month < 12 else "말", text)
        elif month == 12:
            self.assertNotIn("분기", text)
            self.assertNotIn("상반기", text)
        elif month == 6:
            self.assertIn("상반기", text)
        elif month == 9:
            self.assertIn("3분기 누적", text)
        else:
            self.assertIn("1분기", text)

    def test_every_question(self):
        names = {corp: (name, *generator.ALIASES.get(corp, ())) for corp, name in SEALED_EVAL_COMPANIES.items()}
        for question in QUESTIONS:
            text, expected = question["question"], question["expected"]
            with self.subTest(id=question["id"], text=text):
                corp = expected.get("corp_code") or question["grid"].get("corp_code")
                if corp:
                    self.assertTrue(any(name in text for name in names[corp]))
                if expected.get("account"):
                    account = expected["account"]
                    self.assertTrue(ACCOUNTS[account].label in text or generator.SYNONYMS.get(account, "\0") in text)
                if expected.get("fs_div") == "OFS":
                    self.assertIn("별도", text)
                elif question["bundle"] != "A8":
                    self.assertNotIn("별도", text)
                if question["bundle"] == "A8":
                    self.assertIn("연결", text)
                    self.assertIn("별도", text)
                for role in ("period", "current"):
                    if role in expected and question["bundle"] not in ("B6",):
                        self.assertEqual(question["grid"].get(role), expected[role])
                        self.assert_period(text, expected[role], question)

    def test_the_fourth_quarter_is_named(self):
        # the bug found while generating: a fourth-quarter period was written as the whole year
        period = {"kind": "quarter", "year": 2024, "month": 12}
        self.assertEqual(generator.period_text(period, relative=False), "2024년 4분기")
        self.assertEqual(generator.period_text({**period, "kind": "year_to_date"}, relative=False), "2024년")

    def test_particles(self):
        self.assertEqual([generator.josa(word, "은/는") for word in ("매출액", "자산총계", "NAVER", "LG엔솔", "이마트")],
                         ["매출액은", "자산총계는", "NAVER는", "LG엔솔은", "이마트는"])


class FakeResponse:
    def __init__(self, rows, status="000"):
        self.status, self._rows = status, rows

    def json(self):
        return {"list": self._rows}


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def financial_statements(self, corp_code, year, report_code, fs_div):
        return FakeResponse(self.rows)


def row(sj_div, account_id, name, amount, column="thstrm"):
    return {"sj_div": sj_div, "account_id": account_id, "account_nm": name, "account_detail": "-",
            f"{column}_amount": str(amount), "currency": "KRW"}


class RowRuleTests(unittest.TestCase):
    """Contract section 5.3: standard id by statement order, IS/CIS agreement, the gold name table."""

    def select(self, rows, account):
        return gold_rules.select_cell(FakeClient(rows), "00872984", "CFS", account, 2025, "11011", "thstrm")

    def test_income_statement_first_when_the_two_agree(self):
        rows = [row("CIS", "ifrs-full_ProfitLoss", "당기순이익", 5), row("IS", "ifrs-full_ProfitLoss", "당기순이익", 5)]
        self.assertEqual(self.select(rows, "net_income")["sj_div"], "IS")

    def test_the_build_stops_when_the_two_differ(self):
        rows = [row("IS", "ifrs-full_ProfitLoss", "당기순이익", 5), row("CIS", "ifrs-full_ProfitLoss", "당기순이익", 6)]
        with self.assertRaises(GoldError):
            self.select(rows, "net_income")

    def test_a_non_standard_row_by_the_gold_name_table(self):
        rows = [row("CF", "-표준계정코드 미사용-", "영업활동으로부터의 순현금유입", 7)]
        cell = self.select(rows, "operating_cash_flow")
        self.assertEqual(cell["account_nm"], "영업활동으로부터의 순현금유입")
        self.assertTrue(gold_rules.is_non_standard(cell))

    def test_no_row_two_rows_or_an_empty_cell_exclude_the_combination(self):
        for rows in ([], [row("BS", "ifrs-full_Assets", "자산총계", 1), row("BS", "ifrs-full_Assets", "자산총계", 2)],
                     [row("BS", "ifrs-full_Assets", "자산총계", "")]):
            with self.subTest(rows=rows), self.assertRaises(gold_rules.Excluded):
                self.select(rows, "total_assets")

    def test_wording_when_the_sign_changes(self):
        self.assertEqual([gold_rules.direction("operating_income", *pair) for pair in ((5, -3), (-3, 5), (-2, -5), (-5, -2))],
                         ["흑자 전환", "적자 전환", "적자 축소", "적자 확대"])
        self.assertEqual(gold_rules.direction("operating_cash_flow", 5, -3), "증가")


def cases_for(ids, failed=()):
    def score(item):
        ok = item not in failed
        return {"id": item, "automatic_passed": ok, "format_error": None, "status_ok": ok, "decision_ok": True,
                "numbers_ok": ok, "basis_ok": True, "refusal_ok": None, "wording_ok": None, "ungrounded": [], "unparsed": []}
    return [{"id": item, "score": score(item)} for item in ids]


class SampledReviewTests(unittest.TestCase):
    POLICY = {"seed": 3505, "sample": {"crosscheck": 3, "baseline": 2}}
    GOLDS = {f"A1-00{i}": {"bundle": "A1"} for i in range(1, 7)} | {f"A2-00{i}": {"bundle": "A2"} for i in range(1, 4)}

    def test_failures_and_the_drawn_sample_are_required(self):
        cases = cases_for(sorted(self.GOLDS), failed={"A2-001"})
        required, widened = finalize.required_reviews(cases, self.POLICY, "crosscheck", self.GOLDS)
        sample = finalize.review_sample(cases, self.POLICY, "crosscheck")
        self.assertEqual(len(sample), 3)
        self.assertEqual(sorted(required), sorted({"A2-001", *sample}))
        self.assertEqual(widened, [])
        self.assertEqual(finalize.review_sample(cases, self.POLICY, "crosscheck"), sample)  # the same draw every time

    def test_a_sampled_figure_failure_widens_to_its_family(self):
        cases = cases_for(sorted(self.GOLDS))
        sample = finalize.review_sample(cases, self.POLICY, "crosscheck")
        review = {"cases": {sample[0]: {"body_ok": False, "failure_kind": "수치"}}}
        required, widened = finalize.required_reviews(cases, self.POLICY, "crosscheck", self.GOLDS, review)
        family = self.GOLDS[sample[0]]["bundle"]
        self.assertEqual(widened, [family])
        self.assertTrue({item for item, gold in self.GOLDS.items() if gold["bundle"] == family} <= set(required))

    def test_final_scores_need_every_required_review_and_mark_the_rest(self):
        cases = cases_for(sorted(self.GOLDS), failed={"A2-001"})
        required, _ = finalize.required_reviews(cases, self.POLICY, "crosscheck", self.GOLDS)
        review = {"confirmed_by_user": True, "cases": {item: {"body_ok": True} for item in required[:-1]}}
        with self.assertRaises(finalize.ReviewError):
            finalize.final_scores(cases, review, "crosscheck", self.POLICY, self.GOLDS)
        review["cases"][required[-1]] = {"body_ok": True}
        result = finalize.final_scores(cases, review, "crosscheck", self.POLICY, self.GOLDS)
        flags = {item["id"]: item["reviewed"] for item in result["per_case"]}
        self.assertEqual({item for item, flag in flags.items() if flag}, set(required))
        self.assertEqual(result["sample"], finalize.review_sample(cases, self.POLICY, "crosscheck"))
        self.assertEqual(judge.check_sampled_reviews({"crosscheck": ({}, cases)}, {"crosscheck": result}, self.GOLDS,
                                                     self.POLICY), [])
        tampered = copy.deepcopy(result)
        tampered["sample"] = tampered["sample"][:-1]
        self.assertTrue(judge.check_sampled_reviews({"crosscheck": ({}, cases)}, {"crosscheck": tampered}, self.GOLDS,
                                                    self.POLICY))

    def test_the_review_template_lists_only_the_required_answers(self):
        cases = [{**case, "question": "q", "answer": None, "score": {**case["score"], "format_error": None}}
                 for case in cases_for(sorted(self.GOLDS), failed={"A2-001"})]
        required, _ = finalize.required_reviews(cases, self.POLICY, "crosscheck", self.GOLDS)
        template = finalize.review_template(cases, required, self.POLICY)
        self.assertEqual(sorted(template["cases"]), sorted(required))
        self.assertEqual(template["policy"], self.POLICY)


class WrongDirectionTests(unittest.TestCase):
    def case(self, status, numbers_ok=True):
        return {"answer": {"status": status}, "score": {"format_error": None, "numbers_ok": numbers_ok, "basis_ok": True,
                                                        "ungrounded": []}}

    def test_more_careful_with_right_values_is_the_careful_direction(self):
        self.assertEqual(judge.wrong_direction(self.case("확인 필요"), {"expected_status": "비교 가능"}), "조심한 방향")

    def test_less_careful_or_a_wrong_value_is_the_dangerous_direction(self):
        self.assertEqual(judge.wrong_direction(self.case("비교 가능"), {"expected_status": "확인 필요"}), "위험한 방향")
        self.assertEqual(judge.wrong_direction(self.case("확인 필요", numbers_ok=False), {"expected_status": "비교 가능"}),
                         "위험한 방향")


@unittest.skipUnless(gold_rules.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class GeneratedFilesTests(unittest.TestCase):
    def test_the_generator_reproduces_the_committed_files(self):
        self.assertEqual(generator.main(["--check"]), 0)

    def test_the_gold_is_up_to_date_and_every_disagreement_recorded(self):
        self.assertEqual(gold_rules.main(["--check"]), 0)


if __name__ == "__main__":
    unittest.main()
