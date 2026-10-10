"""D4 evaluation tools: the gold builder (eval/d4_gold.py) and the scorer (eval/d4_score.py).

The scorer is checked on hand-made gold and reports: each kind of error it must count (contract 4.3, 4.4, 5).
The gold builder is checked on a sample text PDF whose every value is known (needs pdfplumber).
"""

from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.d4_score import score  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None


def gold(*cells):
    return {"statements": [{"kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 1, "unit_text": "원"}],
            "cells": [{"statement": "연결재무상태표", "kind": "BS", "page": 1, "label": label, "period": period,
                       "printed": printed, "value": value} for label, period, printed, value in cells]}


def report(rows, problems=()):
    return {"statements": [{"title": "연결재무상태표", "page": 1, "problems": list(problems), "rows": [
        {"label": label, "values": [{"column": period, "value": value, "printed": f"{value:,}",
                                     "status": "확인 필요" if flagged else "검사 통과", "page": 1}]}
        for label, period, value, flagged in rows]}], "problems": []}


class ScorerTests(unittest.TestCase):
    GOLD = gold(("유동자산", 0, "1,000", 1000), ("Ⅱ. 비유동자산", 0, "2,000", 2000), ("자산총계", 0, "3,000", 3000))

    def test_everything_right(self):
        result = score(self.GOLD, report([("유동자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                          ("자산총계", 0, 3000, False)]))["totals"]
        self.assertEqual((result["correct"], result["S1"], result["L1"], result["S2"]), (3, 0, 0, 0))

    def test_an_unmarked_wrong_value_is_s1_and_a_marked_one_is_not(self):
        result = score(self.GOLD, report([("유동자산", 0, 1001, False), ("비유동자산", 0, 2000, False),
                                          ("자산총계", 0, 3001, True)]))["totals"]
        self.assertEqual((result["value_wrong"], result["S1"]), (2, 1))

    def test_a_right_value_under_a_wrong_label_is_l1(self):
        # the photo case: "부채" for the line printed "유동부채"
        result = score(self.GOLD, report([("자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                          ("자산총계", 0, 3000, False)]))["totals"]
        self.assertEqual((result["label_wrong"], result["L1"]), (1, 1))

    def test_a_missing_cell_is_s2_unless_a_problem_quotes_it_and_generic_is_g1(self):
        rows = [("유동자산", 0, 1000, False), ("자산총계", 0, 3000, False)]
        self.assertEqual(score(self.GOLD, report(rows))["totals"]["S2"], 1)
        quoted = report(rows, ["1쪽: 원본의 금액 '2,000'를 AI가 읽지 않았다"])
        self.assertEqual(score(self.GOLD, quoted)["totals"]["S2"], 0)
        generic = score(self.GOLD, report(rows, ["AI가 한 부분을 읽지 못했다: budget"]))["totals"]
        self.assertEqual((generic["S2"], generic["G1"]), (1, 1))

    def test_the_same_value_in_another_row_does_not_hide_a_missing_row(self):
        g = gold(("유동자산", 0, "1,000", 1000), ("비유동자산", 0, "1,000", 1000))
        result = score(g, report([("유동자산", 0, 1000, False)]))["totals"]
        self.assertEqual((result["correct"], result["missing"]), (1, 1))

    def test_a_cell_the_gold_does_not_have_is_listed(self):
        result = score(self.GOLD, report([("유동자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                          ("자산총계", 0, 3000, False), ("주석 표의 행", 0, 77, False)]))
        self.assertEqual(result["totals"]["not_in_gold"], 1)


@unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
class GoldBuilderTests(unittest.TestCase):
    def test_the_cells_of_a_sample_pdf(self):
        from dart_review.documents.samples import SampleStatement, text_pdf
        from eval.d4_gold import build
        sample = SampleStatement(
            "재무상태표", "주식회사 예시", ["제 57 기 2025년 12월 31일 현재", "제 56 기 2024년 12월 31일 현재"], "백만원",
            ["제 57 (당) 기", "제 56 (전) 기"],
            [("Ⅰ. 유동자산", ["247,684,612", "227,062,266"]), ("Ⅱ. 비유동자산", ["319,257,498", "-"]),
             ("자산총계", ["566,942,110", "514,531,948"]), ("기본주당이익", ["6,605", "4,950"])])
        items = [{"sj_div": "BS", "account_nm": "유동자산", "thstrm_amount": "247684612000000", "frmtrm_amount": "227062266000000"},
                 {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "566942110000000", "frmtrm_amount": "514531948000000"},
                 {"sj_div": "BS", "account_nm": "부채총계", "thstrm_amount": "130621773000000"}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [sample])
            result = build(path, {"CFS": items})
        cells = {(c["label"], c["period"]): c["value"] for c in result["cells"]}
        self.assertEqual(cells[("유동자산", 0)], 247_684_612_000_000)
        self.assertEqual(cells[("비유동자산", 0)], 319_257_498_000_000)
        self.assertNotIn(("비유동자산", 1), cells)  # a dash is nothing
        self.assertEqual(cells[("기본주당이익", 0)], 6_605)  # per-share amounts are in 원
        whys = sorted((n["why"], n.get("label") or n.get("name")) for n in result["needs_mapping"])
        self.assertIn(("dart_only", "부채총계"), whys)  # in OpenDART, not printed
        self.assertIn(("not_in_dart", "비유동자산"), whys)  # printed, not in OpenDART


if __name__ == "__main__":
    unittest.main()
