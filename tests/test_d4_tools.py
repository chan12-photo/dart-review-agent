"""D4 evaluation tools: the gold builder (eval/d4_gold.py) and the scorer (eval/d4_score.py).

The scorer is checked on hand-made gold and reports: each count it must make (contract 4.3-5), including the
counterexamples of Codex's recheck (one number pointing at two missing rows, an unmarked cell outside the gold, a
statement title printed twice) and third review (free text or another page or period pointing at a cell, verdicts
other than wrong/ok, a product statement outside the gold, a denominator that moved with the product). The gold
builder is checked on a sample PDF and on hand-made lines (a small-amount row near the page bottom, a row whose
label starts with a period word, a statement of small amounts only), and its mapping checks (a cell added twice,
an empty add, no status, notes copied across items).
"""

from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from eval import d4_candidates  # noqa: E402
from eval.d4_candidates import check_pdf, pick_attachment, report_filings  # noqa: E402
from eval.d4_gold import apply_mapping, build  # noqa: E402
from eval.d4_preflight import MODEL, TOOL_PATHS, check, freeze_record, register_record  # noqa: E402
from eval.d4_score import score  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None
SID = "연결재무상태표@1"


CONFIRMED = {"status": "confirmed", "confirmed_by": "user", "confirmed_at": "2026-10-11"}


def gold(*cells, statements=None):
    statements = statements or [{"id": SID, "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 1,
                                 "end_page": 1, "unit_text": "원"}]
    return {"source": {"file": "x.pdf", "sha256": "src"}, "statements": statements, "needs_mapping": [], "mapping": CONFIRMED,
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
        for label, period, value, flagged in rs]} for page, rs, probs in statements], "problems": [], "source_sha256": "src"}


def verdicts(sha=None, by="user", **cells):
    return {"report_sha256": sha, "judged_by": by,
            "verdicts": {cell_id.replace("_", "/"): {"verdict": v, "note": f"{cell_id} 판정 근거"} for cell_id, v in cells.items()}}


class ScorerTests(unittest.TestCase):
    GOLD = gold(cell("유동자산", 0, "1,000", 1000), cell("Ⅱ. 비유동자산", 0, "2,000", 2000),
                cell("자산총계", 0, "3,000", 3000))

    def totals(self, gold_, report_, extras=None, sha=None):
        return score(gold_, report_, extras, sha)["totals"]

    def test_everything_right(self):
        rows = [("유동자산", 0, 1000, False), ("비유동자산", 0, 2000, False), ("자산총계", 0, 3000, False)]
        result = self.totals(self.GOLD, report(rows))
        self.assertEqual((result["correct"], result["S1"], result["L1"], result["S2"]), (3, 0, 0, 0))
        # Codex third review 12: a score of an unsaved report is machine scored, never official
        self.assertEqual(result["status"], {"machine_scored": True, "mapping_confirmed": True, "extras_judged": True,
                                            "scorable": True, "source_verified": True, "report_saved": False,
                                            "official_ready": False})
        self.assertTrue(self.totals(self.GOLD, report(rows), sha="abc")["status"]["official_ready"])

    def test_an_unmarked_wrong_value_is_s1_and_a_marked_one_is_not(self):
        result = self.totals(self.GOLD, report([("유동자산", 0, 1001, False), ("비유동자산", 0, 2000, False),
                                                ("자산총계", 0, 3001, True)]))
        self.assertEqual((result["value_wrong"], result["S1"]), (2, 1))

    def test_a_value_where_the_print_has_a_dash_is_wrong_and_not_a_gold_cell(self):
        # Codex third review 6: the denominator was 1 or 2 for the same gold, by what the product put at the "-"
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("유동자산", 1, "-", None))
        filled = self.totals(g, report([("유동자산", 0, 1000, False), ("유동자산", 1, 101563, False)]))
        self.assertEqual((filled["gold_cells"], filled["correct"], filled["value_wrong"], filled["dash_filled"],
                          filled["S1"]), (1, 1, 0, 1, 1))
        self.assertEqual(filled["S1_parts"]["dash_filled_unmarked"], 1)
        marked = self.totals(g, report([("유동자산", 0, 1000, False), ("유동자산", 1, 101563, True)]))
        self.assertEqual((marked["gold_cells"], marked["dash_filled"], marked["S1"]), (1, 1, 0))
        empty = self.totals(g, report([("유동자산", 0, 1000, False)]))  # nothing where "-" is printed: right
        self.assertEqual((empty["gold_cells"], empty["correct"], empty["dash_filled"], empty["S1"]), (1, 1, 0, 0))

    def test_a_right_value_under_a_wrong_label_is_l1(self):
        result = self.totals(self.GOLD, report([("자산", 0, 1000, False), ("비유동자산", 0, 2000, False),
                                                ("자산총계", 0, 3000, False)]))
        self.assertEqual((result["label_wrong"], result["L1"]), (1, 1))

    def test_a_missing_cell_is_pointed_at_by_a_structured_report(self):
        rows = [("유동자산", 0, 1000, False), ("자산총계", 0, 3000, False)]
        self.assertEqual(self.totals(self.GOLD, report(rows))["S2"], 1)
        for problem in ("1쪽 '비유동자산' 줄 당기: 원본의 금액 '2,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)",
                        "1쪽 '비유동자산' 줄: OCR이 읽은 금액 '2,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)",
                        "1쪽 당기: 원본의 금액 '2,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)",
                        "표에 넣지 못한 금액 2개 (1쪽 '비유동자산' 줄 '2,000', 1쪽 '7'): 줄이나 열을 복원하지 못한 행이 있을 수 "
                        "있다 (원본과 대조 필요)"):
            self.assertEqual(self.totals(self.GOLD, report(rows, [problem]))["S2"], 0, problem)
        generic = self.totals(self.GOLD, report(rows, ["AI가 한 부분을 읽지 못했다: budget"]))
        self.assertEqual((generic["S2"], generic["G1"]), (1, 1))

    def test_free_text_and_another_page_point_at_nothing(self):
        # Codex third review 1: a row and period anywhere in a sentence counted, without its page or its meaning
        rows = [("유동자산", 0, 1000, False), ("자산총계", 0, 3000, False)]
        for problem in ("비유동자산 당기 칸을 읽지 못했다", "비유동자산 당기 값은 정상 확인했다",
                        "9쪽 '비유동자산' 줄 당기: 원본의 금액 '2,000'를 AI가 읽지 않았다",
                        "1쪽 '비유동자산' 줄 전기: 원본의 금액 '2,000'를 AI가 읽지 않았다",
                        "금액 '2,000'을 확인하지 못했다"):
            self.assertEqual(self.totals(self.GOLD, report(rows, [problem]))["S2"], 1, problem)

    def test_a_label_with_parentheses_is_read_whole(self):
        # Codex third review 1: "1쪽 '47' (기타(손실))" was cut to the row "기타(손실"
        g = gold(cell("기타(손실)", 0, "47", 47), cell("기타", 0, "47", 47))
        problem = "표에 넣지 못한 금액 1개 (1쪽 '기타(손실)' 줄 '47'): 줄이나 열을 복원하지 못한 행이 있을 수 있다"
        result = score(g, report([], [problem]))
        self.assertEqual([(c["label"], c["flagged"]) for c in result["statements"][0]["cells"]],
                         [("기타(손실)", True), ("기타", False)])

    def test_a_number_in_both_periods_of_a_row_needs_the_period(self):
        # Codex third review 1: one report without a period counted both periods of the row as pointed at
        g = gold(cell("매출액", 0, "1,000", 1000), cell("매출액", 1, "1,000", 1000))
        without = "1쪽 '매출액' 줄: 원본의 금액 '1,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)"
        self.assertEqual(self.totals(g, report([], [without]))["S2"], 2)
        with_period = "1쪽 '매출액' 줄 전기: 원본의 금액 '1,000'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)"
        result = score(g, report([], [with_period]))
        self.assertEqual([(c["period"], c["flagged"]) for c in result["statements"][0]["cells"]], [(0, False), (1, True)])

    def test_one_number_does_not_point_at_two_missing_rows(self):
        # Codex recheck 1: a warning about '1,000' marked both missing rows printed 1,000
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("비유동자산", 0, "1,000", 1000))
        named = report([], ["1쪽 '유동자산' 줄 당기: 원본의 금액 '1,000'를 AI가 읽지 않았다"])
        self.assertEqual((self.totals(g, named)["missing"], self.totals(g, named)["S2"]), (2, 1))
        bare = report([], ["1쪽 당기: 원본의 금액 '1,000'를 AI가 읽지 않았다"])
        self.assertEqual(self.totals(g, bare)["S2"], 2)  # two rows of the page print it: neither is named

    def test_each_report_points_at_one_cell(self):
        # two rows of one place (the same label, period, and number on a page) need two reports
        g = gold(cell("기타", 0, "5", 5), cell("기타", 0, "5", 5))
        one = "1쪽 '기타' 줄 당기: 원본의 금액 '5'를 AI가 읽지 않았다"
        self.assertEqual(self.totals(g, report([], [one]))["S2"], 1)
        self.assertEqual(self.totals(g, report([], [one, one]))["S2"], 0)

    def test_a_label_on_two_rows_pairs_the_right_row(self):
        # two "기타" rows; the product lost the first: the second is right and the first is missing, not wrong
        g = gold(cell("기타", 0, "5", 5, 1), cell("기타", 0, "7", 7, 2),
                 statements=[{"id": SID, "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 1,
                              "end_page": 2, "unit_text": "원"}])
        rep = report([("기타", 0, 7, False)])
        rep["statements"][0]["rows"][0]["values"][0]["page"] = 2
        result = self.totals(g, rep)
        self.assertEqual((result["correct"], result["value_wrong"], result["missing"], result["S1"]), (1, 0, 1, 0))

    def test_a_label_wrong_pairs_on_the_same_page_first(self):
        # Codex fourth review 5: the third pass took a marked cell of page 1 before the unmarked one of page 2
        g = gold(cell("A", 0, "10", 10, 2), statements=[{"id": SID, "kind": "BS", "title": "연결재무상태표",
                                                          "consolidated": True, "page": 1, "end_page": 2, "unit_text": "원"}])
        rep = report([("B", 0, 10, True), ("C", 0, 10, False)])
        rep["statements"][0]["rows"][1]["values"][0]["page"] = 2
        result = score(g, rep)
        self.assertEqual([(c["product_label"], c["flagged"]) for c in result["statements"][0]["cells"]], [("C", False)])
        self.assertEqual((result["totals"]["L1"], [x["label"] for x in result["statements"][0]["extras"]]), (1, ["B"]))

    def test_a_report_of_another_sign_points_at_nothing(self):
        # Codex fourth review 6: "'47'" pointed at the printed "(47)"
        g = gold(cell("손실", 0, "(47)", -47))
        for problem, s2 in (("1쪽 '손실' 줄 당기: 원본의 금액 '47'를 AI가 읽지 않았다", 1),
                            ("1쪽 '손실' 줄 당기: 원본의 금액 '(47)'를 AI가 읽지 않았다", 0),
                            ("표에 넣지 못한 금액 1개 (1쪽 '손실' 줄 '(47)'): 줄이나 열을 복원하지 못한 행이 있을 수 있다", 0)):
            self.assertEqual(self.totals(g, report([], [problem]))["S2"], s2, problem)

    def test_a_report_of_another_pdf_is_not_scored_and_an_unknown_source_is_not_official(self):
        # Codex fourth review 8: nothing tied the gold, the scan map, and the report to one PDF
        rep = report([("유동자산", 0, 1000, False)])
        with self.assertRaisesRegex(ValueError, "another PDF"):
            score(gold(cell("유동자산", 0, "1,000", 1000)), {**rep, "source_sha256": "other"}, None, "abc")
        del rep["source_sha256"]
        status = self.totals(gold(cell("유동자산", 0, "1,000", 1000)), rep, sha="abc")["status"]
        self.assertEqual((status["source_verified"], status["official_ready"]), (False, False))

    def test_an_unscorable_document_is_never_official(self):
        # Codex fourth review 3: a statement neither the gold nor the product found left an official zero
        g = gold(cell("유동자산", 0, "1,000", 1000))
        g["unscorable"] = ["n3: 현금흐름표를 원본에서 찾지 못했다"]
        status = self.totals(g, report([("유동자산", 0, 1000, False)]), sha="abc")["status"]
        self.assertEqual((status["scorable"], status["official_ready"]), (False, False))

    def test_the_same_value_in_another_row_does_not_hide_a_missing_row(self):
        g = gold(cell("유동자산", 0, "1,000", 1000), cell("비유동자산", 0, "1,000", 1000))
        result = self.totals(g, report([("유동자산", 0, 1000, False)]))
        self.assertEqual((result["correct"], result["missing"]), (1, 1))

    def test_a_statement_the_product_did_not_find_is_missing_cells(self):
        # it made the result "incomplete" before: a statement the product lost is S2, not a reason to stop
        result = self.totals(self.GOLD, {"statements": [], "problems": [], "source_sha256": "src"}, sha="abc")
        self.assertEqual((result["statements_not_found"], result["missing"], result["S2"]), (1, 3, 3))
        self.assertTrue(result["status"]["official_ready"])

    def test_an_unmarked_cell_outside_the_gold_needs_a_verdict_by_its_id(self):
        # Codex recheck 2: it passed S1, L1, and S2 unseen
        g = gold(cell("유동자산", 0, "1,000", 1000))
        rows = [("유동자산", 0, 1000, False), ("주석 표 숫자", 0, 77, False)]
        result = score(g, report(rows))
        self.assertEqual([x["id"] for x in result["statements"][0]["extras"]], ["0/1/0"])
        self.assertEqual((result["totals"]["unjudged_extras"], result["totals"]["status"]["extras_judged"]), (1, False))
        self.assertEqual(self.totals(g, report(rows), verdicts(**{"0_1_0": "wrong"}))["S1"], 1)
        judged = self.totals(g, report(rows), verdicts("abc", **{"0_1_0": "ok"}), sha="abc")
        self.assertEqual((judged["S1"], judged["status"]["official_ready"]), (0, True))
        marked = self.totals(g, report([("유동자산", 0, 1000, False), ("주석 표 숫자", 0, 77, True)]))
        self.assertEqual((marked["unjudged_extras"], marked["status"]["extras_judged"]), (0, True))

    def test_verdicts_are_checked(self):
        # Codex third review 2: "pending" passed as judged, and one key judged two cells
        g = gold(cell("유동자산", 0, "1,000", 1000))
        rows = [("유동자산", 0, 1000, False), ("주석 표", 0, 77, False), ("주석 표", 0, 77, False)]
        cases = [(verdicts("abc", **{"0_1_0": "pending"}), "not 'pending'|'verdict': 'pending'"),
                 (verdicts("abc", **{"0_9_0": "ok"}), "not outside the gold"),
                 ({"report_sha256": "abc", "judged_by": "user", "verdicts": {"0/1/0": {"verdict": "ok"}}}, "note"),
                 (verdicts("abc", by="", **{"0_1_0": "ok"}), "judged_by"),
                 (verdicts("other", **{"0_1_0": "ok"}), "another report")]
        for extras, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                score(g, report(rows), extras, "abc")
        result = self.totals(g, report(rows), verdicts(**{"0_1_0": "wrong"}))
        self.assertEqual((result["not_in_gold"], result["S1"], result["unjudged_extras"]), (2, 1, 1))

    def test_the_cells_of_a_product_statement_outside_the_gold_need_verdicts(self):
        # Codex third review 2: a whole product statement no gold statement took passed as complete
        g = gold(cell("유동자산", 0, "1,000", 1000))
        rep = report([], statements=[(1, [("유동자산", 0, 1000, False)], []), (2, [("가짜행", 0, 999, False)], [])])
        rep["statements"][1]["title"] = "연결현금흐름표"
        result = score(g, rep, None, "abc")
        self.assertEqual(result["totals"]["product_statements_not_in_gold"], ["연결현금흐름표"])
        self.assertEqual((result["totals"]["not_in_gold"], result["totals"]["unjudged_extras"],
                          result["totals"]["status"]["official_ready"]), (1, 1, False))
        judged = score(g, rep, verdicts("abc", **{"1_0_0": "wrong"}), "abc")["totals"]
        self.assertEqual((judged["S1"], judged["status"]["official_ready"]), (1, True))

    def test_a_value_in_a_third_period_is_outside_the_gold(self):
        g = gold(cell("유동자산", 0, "1,000", 1000))
        result = score(g, report([("유동자산", 0, 1000, False), ("유동자산", 2, 900, False)]))
        self.assertEqual([x["id"] for x in result["statements"][0]["extras"]], ["0/1/2"])

    def test_a_draft_mapping_is_never_official(self):
        # also with no item to decide: the development records showed "official" for two documents
        g = gold(cell("유동자산", 0, "1,000", 1000))
        for needs in ([], [{"id": "n1", "why": "dart_only"}]):
            g["needs_mapping"] = needs
            g["mapping"] = {"status": "draft", "confirmed_by": None, "confirmed_at": None}
            status = self.totals(g, report([("유동자산", 0, 1000, False)]), sha="abc")["status"]
            self.assertEqual((status["mapping_confirmed"], status["official_ready"]), (False, False))
            g["mapping"] = CONFIRMED
            self.assertTrue(self.totals(g, report([("유동자산", 0, 1000, False)]), sha="abc")["status"]["official_ready"])
        del g["mapping"]  # a gold the mapping was never applied to
        self.assertFalse(self.totals(g, report([("유동자산", 0, 1000, False)]), sha="abc")["status"]["mapping_confirmed"])

    def test_sums_are_counted_per_statement(self):
        # Codex third review 7: A4 counts statements with sums left unchecked and statements without a check
        rep = report([("유동자산", 0, 1000, False)])
        rep["statements"][0].update(sums_checked=0, sums_uncertain=2)
        result = self.totals(gold(cell("유동자산", 0, "1,000", 1000)), rep)
        self.assertEqual((result["sums_checked"], result["statements_with_uncertain_sums"],
                          result["statements_without_sums"], result["statements_sums_not_checked_by_kind"]), (0, 1, 1, 0))
        rep["statements"][0].update(sums_checked=None, sums_uncertain=0)  # an income statement: not a kind it checks
        result = self.totals(gold(cell("유동자산", 0, "1,000", 1000)), rep)
        self.assertEqual((result["statements_without_sums"], result["statements_sums_not_checked_by_kind"]), (0, 1))

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

    def test_a_row_whose_label_starts_with_a_period_word_is_kept(self):
        # Codex third review 3: "당기순이익 47 48" matched the heading word "당기" and vanished without an item
        heading = words_line([("과 목", 10, 40), ("제", 300, 305), ("57", 310, 320), ("(당)", 322, 335), ("기", 337, 342),
                              ("제", 500, 505), ("56", 510, 520), ("(전)", 522, 535), ("기", 537, 542)], 60)
        unit = words_line([("(단위", 10, 30), (":", 31, 33), ("원)", 34, 45)], 40)
        lines = [unit, heading, line("매출액", "1,000", "2,000", 100), line("당기순이익", "47", "48", 200),
                 line("기본주당이익(단위: 원)", "7", "8", 220)]
        result = self.build_lines(lines, [])
        self.assertEqual(sorted((c["label"], c["printed"]) for c in result["cells"]),
                         [("기본주당이익", "7"), ("기본주당이익", "8"), ("당기순이익", "47"), ("당기순이익", "48"),
                          ("매출액", "1,000"), ("매출액", "2,000")])

    def test_a_statement_without_grouped_amounts_goes_to_a_person(self):
        # Codex third review 3: a statement of small amounts only was emptied without an item
        result = self.build_lines([line("기본주당이익", "47", "48", 100)], [])
        self.assertEqual(result["cells"], [])
        self.assertEqual([(n["why"], n["lines"]) for n in result["needs_mapping"]],
                         [("no_grouped_amounts", ["기본주당이익 47 48"])])

    def test_a_statement_opendart_has_but_the_builder_did_not_find_goes_to_a_person(self):
        lines = [line("매출액", "1,000", "2,000", 100)]
        items = [{"sj_div": sj, "account_nm": n, "thstrm_amount": a, "frmtrm_amount": "0"}
                 for sj, n, a in (("CIS", "매출액", "1000"), ("BS", "자산총계", "5000"), ("CF", "현금", "7"),
                                  ("SCE", "자본", "9"))]
        result = self.build_lines(lines, items)  # the block is a 손익계산서; OpenDART has a 포괄손익계산서 too
        needs = {n["kind"]: n["id"] for n in result["needs_mapping"] if n["why"] == "statement_not_found"}
        self.assertEqual(sorted(needs), ["BS", "CF", "CIS"])  # Codex fourth review 3: IS and CIS are looked for apart
        others = {n["id"]: {"decision": "keep", "note": f"{n['id']} 인쇄 그대로"} for n in result["needs_mapping"]
                  if n["why"] != "statement_not_found"}
        for decision in ({"decision": "ignore"}, {"decision": "same_statement"}):  # no plain ignore; BS has no pair
            with self.assertRaises(ValueError):
                apply_mapping(result, {"status": "draft", "decisions": {**others, needs["BS"]: {**decision, "note": "a"},
                                       needs["CF"]: {"decision": "unscorable", "note": "b"},
                                       needs["CIS"]: {"decision": "same_statement", "note": "c"}}})
        bs = {"id": "연결재무상태표@3", "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 3, "end_page": 3,
              "unit_text": "원"}
        result["source"]["pages"] = 4  # the PDF's page count (None here: the test has no PDF)
        decided = apply_mapping(result, {"status": "draft", "decisions": {
            **others, needs["CIS"]: {"decision": "same_statement", "note": "1쪽 손익계산서가 포괄손익을 함께 보인다"},
            needs["BS"]: {"decision": "add_statement", "note": "3쪽 재무상태표를 사람이 옮겼다", "statement": bs,
                          "cells": [{"statement_id": bs["id"], "page": 3, "label": "자산총계", "period": 0,
                                     "printed": "5,000", "value": 5000}]},
            needs["CF"]: {"decision": "unscorable", "note": "현금흐름표를 원본에서 찾지 못했다"}}})
        self.assertEqual(([s["id"] for s in decided["statements"]], decided["unscorable"]),
                         (["손익계산서@1", "연결재무상태표@3"], [f"{needs['CF']}: 현금흐름표를 원본에서 찾지 못했다"]))
        self.assertIn(("자산총계", 5000), [(c["label"], c["value"]) for c in decided["cells"]])

    def test_amounts_without_separators_go_to_a_person(self):
        # Codex fourth review 2: "매출액 1000 2000" left neither cells nor an item
        only = self.build_lines([line("매출액", "1000", "2000", 100)], [])
        self.assertEqual([(n["why"], n.get("lines")) for n in only["needs_mapping"]],
                         [("no_grouped_amounts", ["매출액 1000 2000"])])
        mixed = self.build_lines([line("매출액", "1,000", "2,000", 100), line("기타", "1000", "-", 120)], [])
        self.assertEqual([(n["why"], n.get("line")) for n in mixed["needs_mapping"] if n["why"] != "not_in_dart"],
                         [("ungrouped_amount", "기타 1000 -")])
        self.assertNotIn("기타", {c["label"] for c in mixed["cells"]})

    def test_amounts_without_separators_can_be_added_and_scored_and_not_ignored_into_an_empty_gold(self):
        # Codex fifth review 1: "1000" could not be added; ignoring the item left 0 gold cells and an official score
        result = self.build_lines([line("매출액", "1000", "2000", 100)], [])
        need = result["needs_mapping"][0]["id"]
        cells = [{"statement_id": "손익계산서@1", "page": 1, "label": "매출액", "period": p, "printed": text, "value": v}
                 for p, text, v in ((0, "1000", 1000), (1, "2000", 2000))]
        confirmed = {"status": "confirmed", "confirmed_by": "user", "confirmed_at": "2026-10-14"}
        added = apply_mapping(result, {**confirmed, "decisions": {need: {"decision": "add", "note": "1쪽 매출액 1000 2000",
                                                                         "cells": cells}}})
        rep = {"statements": [{"title": "손익계산서", "page": 1, "problems": [], "rows": [
            {"label": "매출액", "values": [{"column": 0, "value": 1000, "printed": "1000", "status": "검사 통과", "page": 1}]}]}],
            "problems": [], "source_sha256": None}
        totals = score(added, rep)["totals"]
        self.assertEqual((totals["gold_cells"], totals["correct"], totals["missing"]), (2, 1, 1))
        ignored = apply_mapping(result, {**confirmed, "decisions": {need: {"decision": "ignore", "note": "x"}}})
        self.assertTrue(ignored["unscorable"])
        self.assertFalse(score(ignored, {"statements": [], "problems": []}, None, "abc")["totals"]["status"]["scorable"])

    def test_a_statement_without_any_gold_cell_is_never_official(self):
        # Codex sixth review 1: "no_unit" ignored left a statement of numbers with 0 gold cells, scored official
        lines = [line("매출액", "1,000", "2,000", 100)]
        block = {"id": "연결손익계산서@1", "kind": "IS", "title": "연결손익계산서", "consolidated": True, "page": 1,
                 "end_page": 1, "unit_text": None, "lines": lines}
        with mock.patch("eval.d4_gold.lines_of", return_value=lines), \
                mock.patch("eval.d4_gold.statements_of", return_value=[block]):
            result = build(Path("unused.pdf"), {"CFS": []})
        self.assertEqual([n["why"] for n in result["needs_mapping"]], ["no_unit"])
        decisions = {n["id"]: {"decision": "ignore", "note": "단위 미표기"} for n in result["needs_mapping"]}
        mapped = apply_mapping(result, {"status": "confirmed", "confirmed_by": "user", "confirmed_at": "2026-10-15",
                                        "decisions": decisions})
        self.assertEqual(mapped["unscorable"], ["연결손익계산서@1: 인쇄된 정답 칸이 없는 재무제표"])
        status = score(mapped, {"statements": [], "problems": []}, None, "abc")["totals"]["status"]
        self.assertEqual((status["scorable"], status["official_ready"]), (False, False))
        cells = [{"statement_id": "연결손익계산서@1", "page": 1, "label": "매출액", "period": 0, "printed": "1,000",
                  "value": 1000}]
        added = apply_mapping(result, {"status": "draft", "decisions": {n["id"]: {
            "decision": "add", "note": "1쪽 매출액 1,000: 단위 미표기, 사람이 원으로 확인", "cells": cells}
            for n in result["needs_mapping"]}})
        self.assertEqual(added["unscorable"], [])

    def test_an_added_statement_must_lie_in_the_pdf_and_be_named_by_its_first_page(self):
        # Codex fifth review 5: a statement on page 999 was accepted
        items = [{"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "5000", "frmtrm_amount": "0"}]
        result = self.build_lines([line("매출액", "1,000", "2,000", 100)], items)
        need = next(n["id"] for n in result["needs_mapping"] if n["why"] == "statement_not_found")
        others = {n["id"]: {"decision": "keep", "note": f"{n['id']} 인쇄 그대로"} for n in result["needs_mapping"]
                  if n["id"] != need}

        def decide(page, sid=None, **extra):
            bs = {"id": sid or f"연결재무상태표@{page}", "kind": "BS", "title": "연결재무상태표", "consolidated": True,
                  "page": page, "end_page": page, "unit_text": "원"}
            cell_ = {"statement_id": bs["id"], "page": page, "label": "자산총계", "period": 0, "printed": "5,000", "value": 5000}
            return apply_mapping(result, {"status": "draft", "decisions": {**others, need: {
                "decision": "add_statement", "note": "재무상태표를 사람이 옮겼다", "statement": bs, "cells": [cell_], **extra}}})

        with self.assertRaisesRegex(ValueError, "lie in the PDF"):  # the page count is unknown without the PDF
            decide(3)
        result["source"]["pages"] = 4
        for page, sid, message in ((999, None, "lie in the PDF"), (3, "연결재무상태표@2", "first page"),
                                   (1, None, "shares pages")):
            with self.assertRaisesRegex(ValueError, message):
                decide(page, sid)
        self.assertIn("연결재무상태표@1", [s["id"] for s in decide(1, overlap_note="1쪽 위는 손익계산서, 아래는 재무상태표")["statements"]])
        self.assertIn("연결재무상태표@3", [s["id"] for s in decide(3)["statements"]])

    def test_a_marker_does_not_make_a_second_cell_at_a_place(self):
        # Codex fourth review 4: "Ⅰ. 유동자산" was added beside "유동자산", one printed row counted twice
        lines = [line("유동자산", "1,000", "2,000", 100), line("B계정", "47", "48", 930)]
        result = self.build_lines(lines, [])
        need = next(n["id"] for n in result["needs_mapping"] if n["why"] == "uncertain_line")
        cell_ = {"statement_id": "손익계산서@1", "page": 1, "label": "Ⅰ. 유동자산", "period": 0, "printed": "1,000",
                 "value": 1000}
        others = {n["id"]: {"decision": "keep", "note": f"{n['id']} 인쇄 그대로"} for n in result["needs_mapping"]
                  if n["id"] != need}
        with self.assertRaisesRegex(ValueError, "already"):
            apply_mapping(result, {"status": "draft",
                                   "decisions": {**others, need: {"decision": "add", "note": "x", "cells": [cell_]}}})

    def test_numbers_without_a_label_at_the_page_bottom_go_to_a_person(self):
        lines = [line("매출액", "1,000", "2,000", 100), words_line([("47", 310, 350), ("48", 510, 550)], 940),
                 words_line([("12", 290, 300)], 960)]
        result = self.build_lines(lines, [{"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000",
                                           "frmtrm_amount": "2000"}])
        self.assertEqual([n["why"] for n in result["needs_mapping"]], ["no_label"])  # the page number "12" is dropped

    def test_the_mapping_must_decide_every_item_before_scoring(self):
        lines = [line("매출액", "1,000", "2,000", 100), line("B계정", "47", "48", 930)]
        items = [{"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000", "frmtrm_amount": "2000"}]
        result = self.build_lines(lines, items)
        with self.assertRaisesRegex(ValueError, "no decision"):
            apply_mapping(result, {"status": "draft", "decisions": {}})
        need = next(n for n in result["needs_mapping"] if n["why"] == "uncertain_line")
        decided = apply_mapping(result, {"status": "draft", "decisions": {need["id"]: {"decision": "add", "note": "930쪽 B계정"}}})
        self.assertIn("B계정", {c["label"] for c in decided["cells"]})
        self.assertEqual(decided["mapping"], {"status": "draft", "confirmed_by": None, "confirmed_at": None})

    def test_the_mapping_is_checked(self):
        # Codex third review 5: "add" put an existing cell in twice, an empty "add" passed, nobody had confirmed
        lines = [line("A계정", "1,000", "2,000", 100), line("B계정", "47", "48", 930)]
        result = self.build_lines(lines, [{"sj_div": "IS", "account_nm": "A계정", "thstrm_amount": "1000",
                                           "frmtrm_amount": "2000"}])
        need = next(n for n in result["needs_mapping"] if n["why"] == "uncertain_line")["id"]
        a_cell = {"statement_id": "손익계산서@1", "page": 1, "label": "A계정", "period": 0, "printed": "1,000", "value": 1000}

        def mapping(decision, **extra):
            return {"status": "draft", "decisions": {need: {"note": "1쪽 아래 B계정 47 48", **decision}}, **extra}

        cases = [({"status": None, "decisions": {}}, "status"),
                 (mapping({"decision": "add"}, status="confirmed"), "confirmed_by"),
                 (mapping({"decision": "add", "cells": [a_cell]}), "already"),
                 (mapping({"decision": "add", "cells": []}), "at least one"),
                 (mapping({"decision": "add", "cells": [{**a_cell, "label": "C계정", "value": 1001}]}), "not what"),
                 (mapping({"decision": "add", "cells": [{**a_cell, "label": "C계정", "page": 7}]}), "page"),
                 (mapping({"decision": "add", "cells": [{**a_cell, "label": "C계정", "period": 2}]}), "period"),
                 (mapping({"decision": "add", "note": ""}), "note"),
                 (mapping({"decision": "keep"}), "not one of"),
                 ({"status": "draft", "decisions": {need: {"decision": "add", "note": "x"}, "n99": {"decision": "ignore",
                                                                                                  "note": "y"}}}, "does not have")]
        for value, message in cases:
            with self.assertRaisesRegex(ValueError, message):
                apply_mapping(result, value)
        with self.assertRaisesRegex(ValueError, "not what"):  # 1,000 in 천원, but the statement is in 원
            apply_mapping(result, mapping({"decision": "add", "cells": [{**a_cell, "label": "C계정", "value": 1_000_000}]}))
        added = apply_mapping(result, mapping({"decision": "add", "cells": [{**a_cell, "label": "C계정"}]},
                                              status="confirmed", confirmed_by="user", confirmed_at="2026-10-11"))
        self.assertEqual([(c["label"], c["value"], c["source"]) for c in added["cells"] if c["label"] == "C계정"],
                         [("C계정", 1000, f"mapping:{need}")])
        result["statements"][0]["unit_text"] = "백만원"  # a 백만원 statement: 10^6, or 원 for a per-share row only
        # Codex fourth review 4: "1,000" of an ordinary row passed as 1,000원 in a 백만원 statement
        for label, value, ok in (("C계정", 1_000_000_000, True), ("C계정", 1000, False), ("C계정", 1_000_000, False),
                                 ("기본주당이익", 1000, True)):
            cell_ = {**a_cell, "label": label, "value": value}
            if label == "C계정" and value == 1000:  # a row printed in 원 can still be added, said so explicitly
                apply_mapping(result, mapping({"decision": "add", "cells": [{**cell_, "row_unit": "원"}]}))
            if ok:
                apply_mapping(result, mapping({"decision": "add", "cells": [cell_]}))
            else:
                with self.assertRaisesRegex(ValueError, "not what"):
                    apply_mapping(result, mapping({"decision": "add", "cells": [cell_]}))

    def test_notes_are_not_copied_across_items(self):
        # Codex third review 11: one general note repeated on twelve items stood for twelve checks
        lines = [line("A계정", "1,000", "2,000", 100)]
        result = self.build_lines(lines, [{"sj_div": "IS", "account_nm": n, "thstrm_amount": a, "frmtrm_amount": "0"}
                                          for n, a in (("A계정", "1000"), ("X", "5000"), ("Y", "7000"))])
        ids = [n["id"] for n in result["needs_mapping"] if n["why"] == "dart_only"]
        self.assertEqual(len(ids), 2)
        same = {i: {"decision": "ignore", "note": "OpenDART가 다르게 묶었다"} for i in ids}
        others = {n["id"]: {"decision": "keep", "note": f"{n['id']} 인쇄 그대로"} for n in result["needs_mapping"]
                  if n["id"] not in ids}
        with self.assertRaisesRegex(ValueError, "repeated"):
            apply_mapping(result, {"status": "draft", "decisions": {**same, **others}})


def words_line(words, y, height=1000, page=1):
    words = [{"text": t, "x0": x0, "x1": x1, "top": y, "bottom": y + 8, "page_height": height} for t, x0, x1 in words]
    return {"page": page, "words": words, "text": " ".join(w["text"] for w in words),
            "compact": "".join(w["text"] for w in words), "top": y, "bottom": y + 8}


class D5ToolChangeTests(unittest.TestCase):
    """The two tool defects D4 found on new documents, fixed for D5 (D5 contract draft 3)."""

    def test_dotted_period_lines_start_a_statement(self):
        from eval.d4_gold import statements_of
        # DSR prints "연결 재무상태표" and "제 62 기 2025.12.31 현재": D4's builder found none of its statements
        lines = [words_line([("연결", 200, 220), ("재무상태표", 222, 270)], 54),
                 words_line([("제", 150, 155), ("62", 157, 165), ("기", 167, 172), ("2025.12.31", 175, 230), ("현재", 232, 250)], 69),
                 words_line([("(단위", 400, 420), (":", 421, 423), ("원)", 424, 435)], 90),
                 line("유동자산", "183,887,864,169", "157,101,448,500", 120)]
        blocks = statements_of(lines)
        self.assertEqual([(b["id"], b["unit_text"], len(b["lines"])) for b in blocks], [("연결재무상태표@1", "원", 3)])
        flow = [words_line([("연결", 200, 220), ("현금흐름표", 222, 270)], 54),
                words_line([("제", 150, 155), ("62", 157, 165), ("기", 167, 172), ("2025.01.01", 175, 230), ("부터", 232, 250),
                            ("2025.12.31", 252, 300), ("까지", 302, 320)], 69)]
        self.assertEqual([b["kind"] for b in statements_of(flow)], ["CF"])

    def test_a_dotted_period_line_is_not_a_row(self):
        from eval.d4_gold import _line_kind
        period = words_line([("제", 150, 155), ("62", 157, 165), ("기", 167, 172), ("2025.12.31", 175, 230), ("현재", 232, 250)], 69)
        self.assertEqual(_line_kind(period), "drop")

    def test_a_sentence_or_a_row_with_a_dotted_date_is_not_a_period_line(self):
        # Codex D5 review 4: "2025.12.31 현재" inside a sentence started a statement, inside a row dropped it
        from eval.d4_gold import _line_kind, dated, statements_of
        for text in ("제 62 기 2025.12.31 현재", "제 62 (당) 기 2025.01.01 부터 2025.12.31 까지", "2025.12.31 현재",
                     "제 61 기말 : 2024.12.31 현재", "(2025.12.31 현재)", "제 62 기 2025년 12월 31일 현재"):
            with self.subTest(text=text):
                self.assertTrue(dated(text))
        for text in ("2025.12.31 현재 보증금 47", "2025.12.31 현재 계약조건을 검토했다", "만기 2025.12.31 까지 차입금"):
            with self.subTest(text=text):
                self.assertFalse(dated(text))
        row = words_line([("2025.12.31", 10, 60), ("현재", 62, 80), ("보증금", 82, 110), ("47", 310, 320)], 300)
        self.assertNotEqual(_line_kind(row), "drop")
        sentence = [words_line([("연결재무상태표", 200, 270)], 54),
                    words_line([("2025.12.31", 100, 150), ("현재", 152, 170), ("계약조건을", 172, 220), ("검토했다", 222, 260)], 69)]
        self.assertEqual(statements_of(sentence), [])

    def test_an_untitled_table_is_never_a_gold_statement_and_points_at_nothing(self):
        # D5 contract draft 6 (Codex D5 review): its cells are marked cells outside the gold, the gold's cells are
        # missing and not pointed at (S2 on a text PDF), whatever the table's problem text says
        from dart_review.documents.statement import UNTITLED_REASON, UNTITLED_TITLE
        g = gold(cell("유동자산", 0, "183,887", 183887), cell("자산총계", 0, "391,592", 391592))
        r = {"source_sha256": "src", "problems": [], "statements": [
            {"title": UNTITLED_TITLE, "page": 1, "problems": [UNTITLED_REASON, "1쪽 '유동자산' 줄: 원본의 금액 '9'를 AI가 읽지 않았다"],
             "rows": [{"label": label, "values": [{"column": 0, "value": value, "printed": f"{value:,}", "page": 1,
                                                   "status": "확인 필요"}]}
                      for label, value in (("유동자산", 183887), ("자산총계", 391592))]}]}
        totals = score(g, r)["totals"]
        self.assertEqual((totals["correct"], totals["S1"], totals["S2"], totals["not_in_gold"], totals["unjudged_extras"]),
                         (0, 0, 2, 2, 0))
        self.assertEqual(totals["product_statements_not_in_gold"], [UNTITLED_TITLE])

    def test_labels_compare_without_a_trailing_colon_and_with_one_middle_dot(self):
        from eval.d4_gold import label_key
        # D4: 10 right values counted as wrong labels (현대모비스 "…항목 :", 와이솔 "자산·부채" for "자산ㆍ부채")
        self.assertEqual(label_key("후속적으로 당기손익으로 재분류되지 않는 항목 :"), label_key("후속적으로 당기손익으로 재분류되지 않는 항목"))
        self.assertEqual(label_key("영업활동으로인한자산·부채의변동"), label_key("영업활동으로 인한 자산ㆍ부채의 변동"))
        self.assertEqual(label_key("자산・부채"), "자산ㆍ부채")
        self.assertNotEqual(label_key("당기순손익으로 재분류"), label_key("당기손익으로 재분류"))  # a different word stays different
        self.assertEqual(label_key("Ⅰ. 유동자산 (주석 5)"), "유동자산")

    def test_a_score_counts_the_colon_and_dot_labels_right(self):
        g = gold(cell("후속적으로 당기손익으로 재분류되지 않는 항목", 0, "(166,845)", -166845), cell("자산ㆍ부채의 변동", 0, "1,942", 1942))
        r = report([("후속적으로 당기손익으로 재분류되지 않는 항목 :", 0, -166845, False), ("자산·부채의 변동", 0, 1942, False)])
        totals = score(g, r)["totals"]
        self.assertEqual((totals["correct"], totals["L1"]), (2, 0))


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


class CandidateRuleTests(unittest.TestCase):
    """Codex third review 9: which filing and attachment, and when a PDF counts as not opening, by fixed rules."""

    def test_the_latest_2025_business_report_filing_comes_first(self):
        filings = [{"report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260310", "rcept_no": "20260310000100"},
                   {"report_nm": "[기재정정]사업보고서 (2025.12)", "rcept_dt": "20260320", "rcept_no": "20260320000200"},
                   {"report_nm": "[첨부추가]사업보고서 (2025.12)", "rcept_dt": "20260320", "rcept_no": "20260320000300"},
                   {"report_nm": "사업보고서 (2024.12)", "rcept_dt": "20250310", "rcept_no": "20250310000100"},
                   {"report_nm": "반기보고서 (2025.06)", "rcept_dt": "20250814", "rcept_no": "20250814000100"}]
        self.assertEqual([f["rcept_no"] for f in report_filings(filings)],
                         ["20260320000300", "20260320000200", "20260310000100"])

    def test_the_consolidated_audit_report_attachment(self):
        self.assertEqual(pick_attachment(["감사보고서", "연결내부회계관리제도 감사보고서", "연결 감사보고서", "연결감사보고서(정정)"]),
                         {"position": 3, "name": "연결 감사보고서"})
        self.assertIsNone(pick_attachment(["감사보고서", "내부회계관리제도 감사보고서"]))
        # Codex fourth review 10: "내부 회계" with a space passed the exclusion
        self.assertEqual(pick_attachment(["내부 회계 연결 감사보고서.pdf", "연결감사보고서.pdf"]),
                         {"position": 2, "name": "연결감사보고서.pdf"})

    def test_select_decides_from_recorded_inputs_only(self):
        # Codex fourth review 10: the filing and attachment choice was not run by any tool
        from eval.d4_candidates import select
        filings = [{"report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260310", "rcept_no": "A"},
                   {"report_nm": "[첨부추가]사업보고서 (2025.12)", "rcept_dt": "20260320", "rcept_no": "B"}]
        base = {"corp_code": "001", "induty_code": "264", "filings": filings}
        excluded = ["009"]
        chosen = select({**base, "attachments": {"B": ["감사보고서"], "A": ["감사보고서", "연결감사보고서"]}}, excluded)
        self.assertEqual((chosen["decision"], chosen["rcept_no"], chosen["attachment"]["position"],
                          [c["rcept_no"] for c in chosen["considered"]]), ("받기", "A", 2, ["B", "A"]))
        self.assertEqual(select({**base, "attachments": {"B": ["감사보고서"]}}, excluded)["decision"], "기록 부족")
        self.assertEqual(select({**base, "attachments": {"B": [], "A": []}}, excluded)["reason"], "연결감사보고서 첨부 없음")
        self.assertEqual(select({**base, "induty_code": "6419"}, excluded)["decision"], "제외")
        self.assertEqual(select({**base, "corp_code": "009"}, excluded)["reason"], "개발·봉인 회사")
        self.assertEqual(select({**base, "filings": []}, excluded)["reason"], "사업보고서 (2025.12) 없음")

    def test_select_tells_a_missing_list_from_an_empty_one_and_keeps_the_period(self):
        # Codex fifth review 6: no list.json record read as "no report"; a filing of 2027 was downloaded; the
        # excluded companies came from the input
        from eval.d4_candidates import select
        base = {"corp_code": "001", "induty_code": "264", "excluded_codes": []}
        self.assertEqual(select(base, ["009"])["decision"], "기록 부족")
        late = select({**base, "filings": [{"report_nm": "사업보고서 (2025.12)", "rcept_dt": "20270101", "rcept_no": "C"}],
                       "attachments": {"C": ["연결감사보고서.pdf"]}}, ["009"])
        self.assertEqual((late["decision"], late["reason"], late["out_of_period"]), ("제외", "사업보고서 (2025.12) 없음", ["C"]))
        self.assertEqual(select({**base, "corp_code": "009", "excluded_codes": []}, ["009"])["decision"], "제외")

    def test_a_file_that_is_not_a_pdf_does_not_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x.pdf"
            path.write_bytes(b"not a pdf")
            record = check_pdf(path)
        self.assertEqual((record["verdict"], len(record["sha256"])), ("열리지 않음", 64))

    @unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
    def test_a_text_pdf_is_included_and_a_scan_has_no_text_layer(self):
        from dart_review.documents.samples import SampleStatement, korean_font, scan_pdf, text_pdf
        sample = SampleStatement("재무상태표", "주식회사 예시", ["제 57 기 2025년 12월 31일 현재"], "원", ["당기", "전기"],
                                 [(f"계정{i}", ["1,000", "2,000"]) for i in range(20)])
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(d4_candidates, "MIN_CHARS", 100):
            text = Path(folder) / "text.pdf"
            text_pdf(text, [sample])
            self.assertEqual(check_pdf(text)["verdict"], "포함")
            if korean_font():
                scan = Path(folder) / "scan.pdf"
                scan_pdf(scan, [sample])
                self.assertEqual(check_pdf(scan)["verdict"], "글자 층 없음")


@unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
class ScanTests(unittest.TestCase):
    """Contract 3.3: the statement pages, whole, as images, under fixed conditions, with a page map for the gold."""

    def test_a_scan_of_the_statement_pages(self):
        from dart_review.documents.samples import SampleStatement, text_pdf
        from eval.d4_scan import CONDITIONS, make_scan, scan_gold, statement_pages
        sample = SampleStatement("재무상태표", "주식회사 예시", ["제 57 기 2025년 12월 31일 현재"], "원", ["당기", "전기"],
                                 [(f"계정{i}", ["1,000", "2,000"]) for i in range(20)])
        gold_ = {"statements": [{"id": "재무상태표@2", "kind": "BS", "title": "재무상태표", "page": 2, "end_page": 3}],
                 "source": {"file": "text.pdf", "sha256": None},
                 "cells": [{"statement_id": "재무상태표@2", "page": 3, "label": "계정1", "period": 0, "printed": "1,000",
                            "value": 1000}], "needs_mapping": []}
        self.assertEqual(statement_pages(gold_), [2, 3])
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(d4_candidates, "MIN_CHARS", 100):
            source = Path(folder) / "text.pdf"
            text_pdf(source, [sample, sample, sample, sample])
            import hashlib
            gold_["source"]["sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
            records = {}
            for condition in CONDITIONS:
                out = Path(folder) / f"{condition}.pdf"
                records[condition] = make_scan(source, [2, 3], condition, out)
                self.assertEqual(check_pdf(out)["verdict"], "글자 층 없음")  # images only
                self.assertEqual(check_pdf(out)["pages"], 2)
            again = make_scan(source, [2, 3], "tilt", Path(folder) / "again.pdf")
        self.assertEqual((again["scan_sha256"], again["pixels_sha256"]),
                         (records["tilt"]["scan_sha256"], records["tilt"]["pixels_sha256"]))  # nothing random
        self.assertEqual((records["tilt"]["dpi"], records["tilt"]["rotate"]), (150, 1.0))
        scanned = scan_gold(gold_, records["blur"])
        self.assertEqual((scanned["statements"][0]["page"], scanned["statements"][0]["end_page"],
                          scanned["cells"][0]["page"], scanned["source"]["sha256"]), (1, 2, 2, records["blur"]["scan_sha256"]))
        # Codex fourth review 8: a map with its pages reversed, or of another PDF, was taken
        for bad, message in (({**records["blur"], "pages": [3, 2]}, "pages"),
                             ({**records["blur"], "source_sha256": "0" * 64}, "another PDF")):
            with self.assertRaisesRegex(ValueError, message):
                scan_gold(gold_, bad)

    def test_turning_keeps_the_corners(self):
        # Codex fourth review 7: a 1 degree turn without expand cut the page's corners off
        from PIL import Image
        from eval.d4_scan import CONDITIONS, transform
        image = Image.new("L", (100, 100), 255)
        for x, y in ((0, 0), (99, 0), (0, 99), (99, 99)):
            image.putpixel((x, y), 0)
        turned = transform(image, CONDITIONS["tilt"])
        self.assertGreater(turned.size, (100, 100))
        self.assertLess(turned.getextrema()[0], 200)  # the black corners are still there, if softened
        corners = [turned.crop(box).getextrema()[0] for box in ((0, 0, 6, 6), (turned.width - 6, 0, turned.width, 6),
                                                                (0, turned.height - 6, 6, turned.height),
                                                                (turned.width - 6, turned.height - 6, turned.width, turned.height))]
        self.assertTrue(all(value < 250 for value in corners), corners)


class PreflightTests(unittest.TestCase):
    """Codex third review 8: a commit diff did not see a frozen file changed only in the working tree. Codex fourth
    review 1: the check did not fix the registration commit R, so a gold changed in a later commit passed."""

    ENV = {"python": "3.13.12", "packages": ["pdfplumber==0.11.0"], "model": {MODEL: "abc123"},
           "ollama": "ollama version is 0.34.4", "tesseract": "tesseract 5.5.3", "macos": "27.2"}
    MAPPING = {"status": "confirmed", "confirmed_by": "user", "confirmed_at": "2026-10-11", "decisions": {}}

    def setUp(self):
        import json
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        for path in ("dart_review/__init__.py", "pyproject.toml") + TOOL_PATHS:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(f"# {path}\n", encoding="utf-8")
        self.git("init", "-q")
        self.commit()  # P and T
        self.record = freeze_record(self.root, "HEAD", "HEAD", self.ENV)
        (self.root / "eval/freeze_d4.json").write_text(json.dumps(self.record), encoding="utf-8")
        self.commit()  # F
        (self.root / "eval/gold.json").write_text("preregistered\n", encoding="utf-8")
        (self.root / "eval/a.mapping.json").write_text(json.dumps(self.MAPPING), encoding="utf-8")
        self.commit()
        self.registration = register_record(self.root, "eval/freeze_d4.json", ["eval/gold.json", "eval/a.mapping.json"])
        (self.root / "eval/register_d4.json").write_text(json.dumps(self.registration), encoding="utf-8")
        self.commit()  # R
        self.R = self.head()

    def tearDown(self):
        self.folder.cleanup()

    def git(self, *args, cwd=None):
        import subprocess
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                        "-c", "tag.gpgsign=false", *args], cwd=cwd or self.root, check=True, capture_output=True)

    def head(self):
        import subprocess
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.root, capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")

    def failed(self, env=None, imported_from=None, registered=None, registration=None, remote=None):
        result = check(self.root, self.record, env or self.ENV, imported_from, registration or self.registration,
                       registered or self.R, remote)
        return [c["check"] for c in result["checks"] if not c["ok"]]

    def test_the_registered_checkout_passes(self):
        self.assertEqual(self.failed(imported_from=self.root / "dart_review/__init__.py"), [])

    def test_a_change_only_in_the_working_tree_fails(self):
        (self.root / "eval/d4_score.py").write_text("# changed after the freeze\n", encoding="utf-8")
        self.assertEqual(self.failed(), ["clean working tree and index (git status --porcelain)"])
        self.commit()  # committed: the tree is clean, but HEAD is not R and the tool is not the frozen one
        self.assertEqual(self.failed(), ["HEAD is the registered commit R",
                                         "tools eval/d4_score.py at HEAD is the frozen object"])

    def test_a_gold_changed_after_registration_fails(self):
        (self.root / "eval/gold.json").write_text("changed after seeing results\n", encoding="utf-8")
        self.commit()  # R2
        self.assertEqual(self.failed(), ["HEAD is the registered commit R",
                                         "registered eval/gold.json at HEAD is the recorded object"])
        self.assertEqual(self.failed(registered=self.head()),  # naming R2 as R: the recorded object still differs
                         ["registered eval/gold.json at HEAD is the recorded object"])
        # registering R2 anew passes locally, but the tag pushed at R before the run names R, not R2
        remote = Path(self.folder.name + "-remote")
        self.git("init", "-q", "--bare", str(remote))
        self.git("tag", "-a", "d4-registered", "-m", "R", self.R)
        self.git("push", "-q", str(remote), "refs/tags/d4-registered")
        again = register_record(self.root, "eval/freeze_d4.json", ["eval/gold.json", "eval/a.mapping.json"])
        self.assertEqual(self.failed(registered=self.head(), registration=again), [])
        self.assertEqual(self.failed(registered=self.head(), registration=again, remote=str(remote)),
                         ["the pushed tag d4-registered on " + str(remote) + " names HEAD"])
        self.git("checkout", "-q", self.R)
        self.assertEqual(self.failed(registered="d4-registered", remote=str(remote)), [])
        import shutil
        shutil.rmtree(remote)

    def test_only_committed_files_and_confirmed_mappings_are_registered(self):
        import json
        with self.assertRaisesRegex(ValueError, "eval/none.json is not a file"):
            register_record(self.root, "eval/freeze_d4.json", ["eval/none.json"])
        (self.root / "eval/b.mapping.json").write_text(json.dumps({**self.MAPPING, "status": "draft"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not clean"):
            register_record(self.root, "eval/freeze_d4.json", ["eval/b.mapping.json"])
        self.commit()
        with self.assertRaisesRegex(ValueError, "not a confirmed mapping"):
            register_record(self.root, "eval/freeze_d4.json", ["eval/b.mapping.json"])
        # Codex sixth review (record 1): a draft mapping under another name was accepted
        (self.root / "eval/mapping.json").write_text(json.dumps({**self.MAPPING, "status": "draft"}), encoding="utf-8")
        self.commit()
        with self.assertRaisesRegex(ValueError, "not a confirmed mapping"):
            register_record(self.root, "eval/freeze_d4.json", ["eval/mapping.json"])

    def test_an_untracked_file_and_another_environment_fail(self):
        (self.root / "eval/extra.py").write_text("x", encoding="utf-8")
        self.assertEqual(self.failed(), ["clean working tree and index (git status --porcelain)"])
        (self.root / "eval/extra.py").unlink()
        other = {**self.ENV, "packages": ["pdfplumber==0.11.1"], "model": {MODEL: None}, "ollama": "ollama version is 0.35.0"}
        self.assertEqual(self.failed(other), ["packages as frozen", "model as frozen", "ollama as frozen"])
        self.assertEqual(self.failed(imported_from=Path("/elsewhere/dart_review/__init__.py")),
                         ["dart_review imported from this checkout"])

    def test_a_tool_missing_at_its_commit_cannot_be_frozen(self):
        self.git("rm", "-q", "eval/d4_scan.py")
        self.commit()
        with self.assertRaisesRegex(ValueError, "eval/d4_scan.py"):
            freeze_record(self.root, "HEAD", "HEAD", self.ENV)


class ProfileTests(unittest.TestCase):
    """D5's profile (Codex D5 re-check 1-3): N decided outside the list, the nine tools and P frozen as the code's
    profile names them, its records at their own places, its tag, and no file reached through a link."""

    ENV = PreflightTests.ENV
    MAPPING = PreflightTests.MAPPING

    def setUp(self):
        import json
        from eval.d4_preflight import PROFILES  # the module d4_preflight reads, patched below
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.tools = PROFILES["d5"]["tool_paths"]
        for path in ["dart_review/__init__.py", "pyproject.toml", *self.tools]:
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_text(f"# {path}\n", encoding="utf-8")
        self.git("init", "-q")
        self.commit()  # P and T
        self.P = self.head()
        self.enterContext(mock.patch.dict(PROFILES["d5"], {"product_commit": self.P}))
        self.record = freeze_record(self.root, "HEAD", "HEAD", self.ENV, "d5", 2)
        (self.root / "eval/freeze_d5.json").write_text(json.dumps(self.record), encoding="utf-8")
        self.commit()  # F, tagged and the tag pushed at ④ (Codex D5 third review 1)
        self.F = self.head()
        import shutil
        self.remote = str(Path(self.folder.name + "-remote"))
        self.git("init", "-q", "--bare", self.remote)
        self.addCleanup(shutil.rmtree, self.remote)
        self.git("tag", "-a", "d5-frozen", "-m", "F", self.F)
        self.git("push", "-q", self.remote, "refs/tags/d5-frozen")
        self.documents = {"expected_documents": 2, "documents": []}
        self.paths = ["eval/d5_eval/documents.json", "eval/d5_eval/duplicate_places.json"]
        for n in (1, 2):
            scans = {c: {"pdf": f"{n}.{c}.pdf", "sha256": f"s{n}{c}", "map": f"eval/d5_eval/scans/{n}.{c}.map.json"}
                     for c in ("normal", "tilt", "blur")}
            item = {"key": f"{n}", "rank": 19 + n, "corp_code": f"c{n}", "pdf": f"{n}.pdf", "sha256": f"t{n}",
                    "gold": f"eval/d5_eval/gold/{n}.gold.json", "mapping": f"eval/d5_eval/gold/{n}.mapping.json",
                    "scans": scans}
            self.documents["documents"].append(item)
            for path in (item["gold"], item["mapping"], *(scan["map"] for scan in scans.values())):
                (self.root / path).parent.mkdir(parents=True, exist_ok=True)
                (self.root / path).write_text(json.dumps(self.MAPPING if "mapping" in path else {}), encoding="utf-8")
                self.paths.append(path)
        self.write("eval/d5_eval/documents.json", self.documents)
        self.write("eval/d5_eval/duplicate_places.json", {"documents": {}})
        self.commit()
        self.registration = register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", self.remote)
        self.write("eval/register_d5.json", self.registration)
        self.commit()  # R
        self.R = self.head()
        self.git("tag", "-a", "d5-registered", "-m", "R", self.R)

    git, head, commit = PreflightTests.git, PreflightTests.head, PreflightTests.commit

    def write(self, path, data):
        import json
        (self.root / path).write_text(json.dumps(data), encoding="utf-8")

    def failed(self, record=None, registration=None, registered="d5-registered", remote=None):
        result = check(self.root, record or self.record, self.ENV, None, registration or self.registration, registered,
                       remote, "d5")
        self.assertEqual(result["profile"], "d5")
        return [c["check"] for c in result["checks"] if not c["ok"]]

    def test_the_profile_is_frozen_with_its_nine_tools_and_n(self):
        self.assertEqual(sorted(self.record["objects"]["tools"]), sorted(self.tools))
        self.assertEqual(len(self.tools), 9)
        self.assertEqual((self.record["profile"]["expected_documents"], self.record["profile"]["tag"]), (2, "d5-registered"))
        self.assertEqual((self.registration["profile"], self.registration["tag"]), ("d5", "d5-registered"))
        self.assertEqual(self.failed(), [])

    def test_another_p_or_no_n_cannot_be_frozen(self):
        self.write("dart_review/__init__.py", "changed")
        self.commit()
        with self.assertRaisesRegex(ValueError, "product commit"):
            freeze_record(self.root, "HEAD", "HEAD", self.ENV, "d5", 2)
        for count in (None, 0, True, "10"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                freeze_record(self.root, self.P, "HEAD", self.ENV, "d5", count)
        with self.assertRaises(ValueError):
            freeze_record(self.root, self.P, "HEAD", self.ENV, "d4", 10)

    def test_a_tool_changed_after_the_freeze_fails(self):
        (self.root / "eval/d4_eval/run_d4.py").write_text("# runner changed after the freeze\n", encoding="utf-8")
        self.commit()
        self.assertIn("tools eval/d4_eval/run_d4.py at HEAD is the frozen object",
                      self.failed(registered=self.head()))

    def test_r_is_named_by_its_tag_and_the_registration_is_the_profile_s(self):
        self.assertEqual(self.failed(registered=self.R), ["R is named by the tag d5-registered"])
        d4_like = {k: v for k, v in self.registration.items() if k not in ("profile", "tag")}
        self.assertEqual(self.failed(registration=d4_like),
                         ["the registration is d5's, with its tag and freeze record"])
        changed = {**self.record, "profile": {**self.record["profile"], "tool_paths": self.tools[:5]}}
        self.assertIn("the freeze record holds the d5 profile", self.failed(record=changed))
        self.assertEqual(self.failed(remote=self.remote), ["the pushed tag d5-registered on " + self.remote + " names HEAD"])
        self.git("push", "-q", self.remote, "refs/tags/d5-registered")
        self.assertEqual(self.failed(remote=self.remote), [])

    def test_the_registration_holds_the_whole_list_at_the_frozen_n(self):
        with self.assertRaisesRegex(ValueError, "not registered: eval/d5_eval/gold/2.gold.json"):
            register_record(self.root, "eval/freeze_d5.json",
                            [p for p in self.paths if p != "eval/d5_eval/gold/2.gold.json"], "d5", self.remote)
        with self.assertRaisesRegex(ValueError, "registers its freeze record"):
            register_record(self.root, "eval/d5_eval/duplicate_places.json", self.paths, "d5", self.remote)
        # Codex D5 re-check 1: one of the decided documents, its list saying 1
        self.write("eval/d5_eval/documents.json", {"expected_documents": 1, "documents": self.documents["documents"][:1]})
        self.commit()
        with self.assertRaisesRegex(ValueError, "the profile 2"):
            register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", self.remote)

    def test_a_link_is_never_registered(self):
        import os
        outside = Path(self.folder.name + "-outside.json")
        outside.write_text("{}", encoding="utf-8")
        self.addCleanup(outside.unlink)
        os.symlink(outside, self.root / "eval/d5_eval/gold/link.gold.json")
        self.commit()
        with self.assertRaisesRegex(ValueError, "link.gold.json is not a file inside the repository"):
            register_record(self.root, "eval/freeze_d5.json", [*self.paths, "eval/d5_eval/gold/link.gold.json"], "d5",
                            self.remote)

    def test_n_changed_between_f_and_r_is_refused(self):
        # Codex D5 third review 1: N = 2 frozen at F, then N and the list both made 1 before R
        import json
        self.write("eval/freeze_d5.json", {**self.record, "profile": {**self.record["profile"], "expected_documents": 1}})
        self.write("eval/d5_eval/documents.json", {"expected_documents": 1, "documents": self.documents["documents"][:1]})
        self.commit()
        with self.assertRaisesRegex(ValueError, "not the record frozen at F"):
            register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", self.remote)
        # a registration made by hand from the changed record: the check finds it is not F's
        changed = json.loads((self.root / "eval/freeze_d5.json").read_text(encoding="utf-8"))
        forged = {**self.registration, "freeze_object": self.object_at("HEAD", "eval/freeze_d5.json"),
                  "objects": {**self.registration["objects"],
                              "eval/freeze_d5.json": self.object_at("HEAD", "eval/freeze_d5.json")}}
        self.assertIn("F (d5-frozen) is the registration's, its freeze record the one at HEAD",
                      self.failed(record=changed, registration=forged, registered=self.head()))

    def test_f_must_be_tagged_and_pushed(self):
        self.git("push", "-q", self.remote, ":refs/tags/d5-frozen")
        with self.assertRaisesRegex(ValueError, "does not name"):
            register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", self.remote)
        with self.assertRaisesRegex(ValueError, "does not name"):
            register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", None)
        self.assertIn(f"the pushed tag d5-frozen on {self.remote} names F", self.failed(remote=self.remote))
        self.git("tag", "-d", "d5-frozen")
        with self.assertRaisesRegex(ValueError, "no tag d5-frozen"):
            register_record(self.root, "eval/freeze_d5.json", self.paths, "d5", self.remote)
        self.assertIn("F (d5-frozen) is the registration's, its freeze record the one at HEAD", self.failed())

    def test_a_registration_record_linked_out_of_the_repository_fails_the_check(self):
        # Codex D5 third review 2: R's own record was a link to a file outside, changed after R
        import os
        outside = Path(self.folder.name + "-register.json")
        outside.write_text((self.root / "eval/register_d5.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.addCleanup(outside.unlink)
        (self.root / "eval/register_d5.json").unlink()
        os.symlink(outside, self.root / "eval/register_d5.json")
        self.commit()
        self.assertIn("eval/register_d5.json is a regular file at HEAD, reached without a link",
                      self.failed(registered=self.head()))

    def object_at(self, commit, path):
        import subprocess
        return subprocess.run(["git", "rev-parse", f"{commit}:{path}"], cwd=self.root, capture_output=True,
                              text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
