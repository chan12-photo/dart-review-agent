"""D4 evaluation tools: the gold builder (eval/d4_gold.py) and the scorer (eval/d4_score.py).

The scorer is checked on hand-made gold and reports: each count it must make (contract 4.3-5), including the
counterexamples of Codex's recheck: one number pointing at two missing rows, an unmarked cell outside the gold,
a statement title printed twice. The gold builder is checked on a sample PDF and on hand-made lines (a small-amount
row near the page bottom, the same amounts on two rows).
"""

from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval.d4_gold import apply_mapping, build  # noqa: E402
from eval.d4_score import score  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None
SID = "연결재무상태표@1"


def gold(*cells, statements=None):
    statements = statements or [{"id": SID, "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 1,
                                 "end_page": 1, "unit_text": "원"}]
    return {"statements": statements, "needs_mapping": [],
            "cells": [{"statement_id": sid, "statement": "연결재무상태표", "kind": "BS", "page": page, "label": label,
                       "period": period, "printed": printed, "value": value}
                      for sid, page, label, period, printed, value in cells]}


def cell(label, period, printed, value, page=1, sid=SID):
    return (sid, page, label, period, printed, value)


def report(rows, problems=(), statements=None):
    statements = statements or [(1, rows, list(problems))]
    return {"statements": [{"title": "연결재무상태표", "page": page, "problems": probs, "rows": [
        {"label": label, "values": [{"column": period, "value": value, "printed": f"{value:,}",
                                     "status": "확인 필요" if flagged else "검사 통과", "page": page}]}
        for label, period, value, flagged in rs]} for page, rs, probs in statements], "problems": []}


class ScorerTests(unittest.TestCase):
    GOLD = gold(cell("유동자산", 0, "1,000", 1000), cell("Ⅱ. 비유동자산", 0, "2,000", 2000),
                cell("자산총계", 0, "3,000", 3000))

    def totals(self, gold_, report_, extras=None):
        return score(gold_, report_, extras)["totals"]

    def test_everything_right(self):
        result = self.totals(self.GOLD, report([("유동자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                                ("자산총계", 0, 3000, False)]))
        self.assertEqual((result["correct"], result["S1"], result["L1"], result["S2"], result["complete"]),
                         (3, 0, 0, 0, True))

    def test_an_unmarked_wrong_value_is_s1_and_a_marked_one_is_not(self):
        result = self.totals(self.GOLD, report([("유동자산", 0, 1001, False), ("비유동자산", 0, 2000, False),
                                                ("자산총계", 0, 3001, True)]))
        self.assertEqual((result["value_wrong"], result["S1"]), (2, 1))

    def test_a_value_where_the_print_has_a_dash_is_wrong(self):
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("유동자산", 1, "-", None))
        result = self.totals(g, report([("유동자산", 0, 1000, False), ("유동자산", 1, 101563, False)]))
        self.assertEqual((result["correct"], result["value_wrong"], result["S1"]), (1, 1, 1))
        result = self.totals(g, report([("유동자산", 0, 1000, False)]))  # nothing where "-" is printed: right
        self.assertEqual((result["correct"], result["gold_cells"], result["S1"]), (1, 1, 0))

    def test_a_right_value_under_a_wrong_label_is_l1(self):
        result = self.totals(self.GOLD, report([("자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                                ("자산총계", 0, 3000, False)]))
        self.assertEqual((result["label_wrong"], result["L1"]), (1, 1))

    def test_a_missing_cell_is_pointed_at_by_its_number_and_row(self):
        rows = [("유동자산", 0, 1000, False), ("자산총계", 0, 3000, False)]
        self.assertEqual(self.totals(self.GOLD, report(rows))["S2"], 1)
        ai = report(rows, ["1쪽 '비유동자산' 줄: 원본의 금액 '2,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)"])
        self.assertEqual(self.totals(self.GOLD, ai)["S2"], 0)
        rules = report(rows, ["표에 넣지 못한 금액 1개 (1쪽 '2,000' (비유동자산)): 줄이나 열을 복원하지 못한 행이 있을 수 있다"])
        self.assertEqual(self.totals(self.GOLD, rules)["S2"], 0)
        number_only = report(rows, ["1쪽: 원본의 금액 '2,000'를 AI가 읽지 않았다"])  # unique in the statement
        self.assertEqual(self.totals(self.GOLD, number_only)["S2"], 0)
        row_and_period = report(rows, ["비유동자산 당기 칸을 읽지 못했다"])  # Codex recheck: allowed by contract 4.4
        self.assertEqual(self.totals(self.GOLD, row_and_period)["S2"], 0)
        generic = self.totals(self.GOLD, report(rows, ["AI가 한 부분을 읽지 못했다: budget"]))
        self.assertEqual((generic["S2"], generic["G1"]), (1, 1))

    def test_one_number_does_not_point_at_two_missing_rows(self):
        # Codex recheck 1: a warning about '1,000' marked both missing rows printed 1,000
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("비유동자산", 0, "1,000", 1000))
        named = report([], ["1쪽 '유동자산' 줄: 원본의 금액 '1,000'를 AI가 읽지 않았다"])
        self.assertEqual((self.totals(g, named)["missing"], self.totals(g, named)["S2"]), (2, 1))
        bare = report([], ["유동자산 당기 원본 금액 '1,000'을 읽지 않았다"])
        self.assertEqual(self.totals(g, bare)["S2"], 1)  # the row-and-period wording points at 유동자산 only

    def test_the_same_value_in_another_row_does_not_hide_a_missing_row(self):
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("비유동자산", 0, "1,000", 1000))
        result = self.totals(g, report([("유동자산", 0, 1000, False)]))
        self.assertEqual((result["correct"], result["missing"]), (1, 1))

    def test_an_unmarked_cell_outside_the_gold_needs_a_verdict(self):
        # Codex recheck 2: it passed S1, L1, and S2 unseen
        g = gold(cell("유동자산", 0, "1,000", 1000))
        rows = [("유동자산", 0, 1000, False), ("주석 표 숫자", 0, 77, False)]
        result = self.totals(g, report(rows))
        self.assertEqual((result["not_in_gold"], result["unjudged_extras"], result["complete"]), (1, 1, False))
        key = f"{SID}|주석 표 숫자|0|77"
        self.assertEqual(self.totals(g, report(rows), {key: "wrong"})["S1"], 1)
        self.assertEqual(self.totals(g, report(rows), {key: "ok"})["complete"], True)
        marked = self.totals(g, report([("유동자산", 0, 1000, False), ("주석 표 숫자", 0, 77, True)]))
        self.assertEqual((marked["unjudged_extras"], marked["complete"]), (0, True))

    def test_a_title_printed_twice_is_two_statements(self):
        # Codex recheck 4: both were scored twice (gold_cells 4, missing 2)
        statements = [{"id": "연결재무상태표@1", "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 1,
                       "end_page": 2, "unit_text": "원"},
                      {"id": "연결재무상태표@5", "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 5,
                       "end_page": 5, "unit_text": "원"}]
        g = gold(cell("유동자산", 0, "1,000", 1000, 1, "연결재무상태표@1"),
                 cell("유동자산", 0, "1,000", 1000, 5, "연결재무상태표@5"), statements=statements)
        rep = report([], statements=[(1, [("유동자산", 0, 1000, False)], []), (5, [("유동자산", 0, 1000, False)], [])])
        result = self.totals(g, rep)
        self.assertEqual((result["gold_cells"], result["correct"], result["missing"]), (2, 2, 0))


def line(label, a, b, y, height=1000, page=1):
    words = [{"text": t, "x0": x0, "x1": x1, "top": y, "bottom": y + 8, "page_height": height}
             for t, x0, x1 in ((label, 10, 80), (a, 310, 350), (b, 510, 550))]
    return {"page": page, "words": words, "text": " ".join(w["text"] for w in words),
            "compact": "".join(w["text"] for w in words), "top": y, "bottom": y + 8}


class GoldBuilderTests(unittest.TestCase):
    def build_lines(self, lines, items):
        block = {"id": "손익계산서@1", "kind": "IS", "title": "손익계산서", "consolidated": True, "page": 1, "end_page": 1,
                 "unit_text": "원", "lines": lines}
        with mock.patch("eval.d4_gold.lines_of", return_value=lines), \
                mock.patch("eval.d4_gold.statements_of", return_value=[block]):
            return build(Path("unused.pdf"), {"CFS": items})

    def test_a_small_amount_row_near_the_page_bottom_is_not_dropped(self):
        # Codex recheck 3: it vanished from the gold without a mapping item
        lines = [line("매출액", "1,000", "2,000", 100), line("A계정", "47", "48", 200), line("B계정", "47", "48", 930)]
        items = [{"sj_div": "IS", "account_nm": n, "thstrm_amount": a, "frmtrm_amount": b}
                 for n, a, b in (("매출액", "1000", "2000"), ("A계정", "47", "48"), ("B계정", "47", "48"))]
        result = self.build_lines(lines, items)
        labels = {c["label"] for c in result["cells"]}
        self.assertEqual(labels, {"매출액", "A계정"})
        whys = [(n["why"], n.get("line", n.get("name"))) for n in result["needs_mapping"]]
        self.assertIn("uncertain_line", [w for w, _ in whys])  # B계정 goes to a person
        self.assertEqual(sorted(n["name"] for n in result["needs_mapping"] if n["why"] == "dart_only"), ["B계정", "B계정"])

    def test_the_mapping_must_decide_every_item_before_scoring(self):
        lines = [line("매출액", "1,000", "2,000", 100), line("B계정", "47", "48", 930)]
        items = [{"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000", "frmtrm_amount": "2000"}]
        result = self.build_lines(lines, items)
        with self.assertRaisesRegex(ValueError, "no decision"):
            apply_mapping(result, {"decisions": {}})
        need = next(n for n in result["needs_mapping"] if n["why"] == "uncertain_line")
        decided = apply_mapping(result, {"decisions": {need["id"]: {"decision": "add"}}, "confirmed_by": "user"})
        self.assertIn("B계정", {c["label"] for c in decided["cells"]})


@unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
class GoldBuilderPdfTests(unittest.TestCase):
    def test_the_cells_of_a_sample_pdf(self):
        from dart_review.documents.samples import SampleStatement, text_pdf
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
        self.assertIsNone(cells[("비유동자산", 1)])  # a dash: printed nothing
        self.assertEqual(cells[("기본주당이익", 0)], 6_605)  # per-share amounts are in 원
        whys = sorted((n["why"], n.get("label") or n.get("name")) for n in result["needs_mapping"])
        self.assertIn(("dart_only", "부채총계"), whys)
        self.assertIn(("not_in_dart", "비유동자산"), whys)
        self.assertTrue(all(n["id"].startswith("n") for n in result["needs_mapping"]))


if __name__ == "__main__":
    unittest.main()
