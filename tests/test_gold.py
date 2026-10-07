"""Tests for the gold builder: its own reader and arithmetic, and that the cross-check catches disagreements."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import build_gold  # noqa: E402
from build_gold import GoldError, build, change_of, cross_check, read_cell, validate_spec  # noqa: E402
from dart_review import facts, periods, review  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import SealedCompanyError  # noqa: E402
from dart_review.periods import instant  # noqa: E402

CORP = "00126380"


def no_key():
    raise AssertionError("must not need the key")


def load_spec():
    return json.loads(build_gold.SPEC.read_text(encoding="utf-8"))


class ArithmeticTests(unittest.TestCase):
    def test_rate_is_rounded_half_up(self):
        self.assertEqual(change_of(101_005, 100_000, None), {"change": 1005, "change_pct": "1.01", "direction": "증가"})
        self.assertEqual(change_of(90, 100, None)["direction"], "감소")

    def test_sign_change_needs_a_stated_direction(self):
        with self.assertRaises(GoldError):
            change_of(5, -3, None)
        self.assertEqual(change_of(5, -3, "흑자 전환"), {"change": 8, "change_pct": None, "direction": "흑자 전환"})
        with self.assertRaises(GoldError):
            change_of(90, 100, "증가")


class ReaderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.cache = ResponseCache(Path(temp.name))
        self.client = DartClient(self.cache, key_loader=no_key, offline=True)

    def store(self, rows, status="000"):
        body = json.dumps({"status": status, "message": "", "list": rows}, ensure_ascii=False).encode("utf-8")
        params = {"corp_code": CORP, "bsns_year": "2025", "reprt_code": "11011", "fs_div": "CFS"}
        self.cache.put("fnlttSinglAcntAll.json", params, body, status, "", "2026-10-07T00:00:00+00:00")

    def row(self, amount, detail="-"):
        return {"rcept_no": "20260310000001", "sj_div": "IS", "account_id": "ifrs-full_Revenue", "account_nm": "매출액",
                "account_detail": detail, "thstrm_amount": amount, "currency": "KRW"}

    CELL = {"year": 2025, "report_code": "11011", "column": "thstrm", "sj_div": "IS", "account_id": "ifrs-full_Revenue"}

    def test_reads_exactly_one_total_row(self):
        self.store([self.row("10"), self.row("99", detail="부문 [member]")])
        self.assertEqual(read_cell(self.client, CORP, "CFS", self.CELL)["amount"], 10)

    def test_refuses_duplicates_odd_amounts_and_wrong_status(self):
        for rows in ([self.row("1"), self.row("2")], [self.row("1.5")], [self.row("")]):
            with self.subTest(rows=rows):
                self.store(rows)
                with self.assertRaises(GoldError):
                    read_cell(self.client, CORP, "CFS", self.CELL)
        self.store([], status="013")
        with self.assertRaises(GoldError):
            read_cell(self.client, CORP, "CFS", self.CELL)
        self.assertEqual(read_cell(self.client, CORP, "CFS", {"year": 2025, "report_code": "11011", "expect_status": "013"})["status"], "013")


class SpecTests(unittest.TestCase):
    def test_every_case_type_is_covered(self):
        spec = load_spec()
        validate_spec(spec)
        spec["questions"] = [q for q in spec["questions"] if "데이터 없음" not in q["case_types"]]
        with self.assertRaises(GoldError):
            validate_spec(spec)

    def test_sealed_companies_are_refused(self):
        spec = load_spec()
        spec["questions"][0]["expected"]["corp_code"] = "00266961"
        with self.assertRaises(SealedCompanyError):
            validate_spec(spec)


@unittest.skipUnless(build_gold.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class CacheGoldTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(build_gold.CACHE), key_loader=no_key, offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def question(self, question_id, spec=None):
        spec = spec or load_spec()
        return next(q for q in spec["questions"] if q["id"] == question_id)

    def problems(self, question):
        return cross_check(self.client, question, build_gold.build_question(self.client, question))

    def test_committed_gold_is_current_and_agrees_with_the_rules(self):
        document, problems = build(self.client, load_spec())
        self.assertEqual(problems, [])
        self.assertEqual(build_gold.render(document), build_gold.GOLD.read_text(encoding="utf-8"))

    def test_wrong_hand_evidence_is_caught(self):
        # the naive reading: the 2025 Q3 report's prior column as "last year's Q3 end"
        question = copy.deepcopy(self.question("dev02"))
        question["expected"]["evidence"]["base"] = {"year": 2025, "report_code": "11014", "column": "frmtrm",
                                                    "sj_div": "BS", "account_id": "ifrs-full_Assets"}
        self.assertTrue(any("base value or source differs" in problem for problem in self.problems(question)))

    def test_wrong_expected_status_is_caught(self):
        question = copy.deepcopy(self.question("dev08"))
        question["expected"]["status"] = "비교 가능"
        question["expected"].pop("reason_keywords")
        self.assertTrue(any(problem.startswith("status:") for problem in self.problems(question)))

    def test_a_rule_bug_is_caught(self):
        original = periods.column_periods

        def naive(year, report_code, sj_div):
            columns = original(year, report_code, sj_div)
            if sj_div == "BS" and report_code != "11011":
                columns = {**columns, "frmtrm": instant(year - 1, periods.REPORT_END_MONTH[report_code])}
            return columns

        with mock.patch.object(periods, "column_periods", naive), mock.patch.object(facts, "column_periods", naive), \
                mock.patch.object(review, "column_periods", naive):
            problems = self.problems(self.question("dev02"))
        self.assertTrue(any("base value or source differs" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
