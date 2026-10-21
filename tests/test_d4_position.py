"""The D4 position check (eval/d4_eval/position_check.py): rows sharing a label in a statement, checked by order."""

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

import position_check as pc  # noqa: E402
from eval.d4_gold import apply_mapping  # noqa: E402

STATEMENT = {"id": "연결재무상태표@10", "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 10,
             "end_page": 11, "unit_text": "원"}


def gold_cell(label, period, printed, value, page=10):
    return {"statement_id": STATEMENT["id"], "statement": STATEMENT["title"], "kind": "BS", "page": page, "label": label,
            "period": period, "printed": printed, "value": value}


def gold_order(gold):
    """Registered places in the gold's cell order (the print order of these fixtures and of the gold builder)."""
    return [{"id": pc.place_id(*k), "statement_id": k[0], "key": k[1], "period": k[2],
             "rows": [{"page": c["page"], "top": n, "label": c["label"], "printed": c["printed"], "value": c["value"]}
                      for n, c in enumerate(v)]} for k, v in pc.places_of(gold).items()]


class Fixture(unittest.TestCase):
    """One document: '파생상품' on two rows of page 10 (204 above, 54 below), a '-' place, and '충당부채' on page 10
    (300) and page 11 (400)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        cells = [gold_cell("파생상품", 0, "204", 204), gold_cell("파생상품", 1, "77", 77),
                 gold_cell("파생상품", 0, "54", 54), gold_cell("파생상품", 1, "20", 20),
                 gold_cell("기타", 0, "-", None), gold_cell("기타", 0, "100", 100),
                 gold_cell("충당부채", 0, "300", 300), gold_cell("충당부채", 0, "400", 400, page=11)]
        gold = {"source": {"file": "a.pdf", "sha256": "src", "pages": 20}, "statements": [STATEMENT], "cells": cells,
                "needs_mapping": []}
        (self.dir / "a.gold.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
        (self.dir / "a.mapping.json").write_text(json.dumps({"status": "confirmed", "confirmed_by": "t", "confirmed_at": "t",
                                                              "decisions": {}}), encoding="utf-8")
        self.document = {"key": "a", "sha256": "src", "gold": str(self.dir / "a.gold.json"),
                         "mapping": str(self.dir / "a.mapping.json")}
        self.write_gold(gold)

    def write_gold(self, gold):
        """The gold and the places registered from it (in the gold's order)."""
        (self.dir / "a.gold.json").write_text(json.dumps(gold, ensure_ascii=False), encoding="utf-8")
        applied = apply_mapping(gold, json.loads((self.dir / "a.mapping.json").read_text()))
        self.registered = {"documents": {"a": {"pdf_sha256": "src", "places": gold_order(applied)}}}

    def report(self, rows, title="연결재무상태표", page=10, source="src"):
        return {"source_sha256": source, "problems": [],
                "statements": [{"title": title, "page": page, "rows": rows, "problems": []}]}

    def row(self, label, values, page=10, flagged=False):
        return {"label": label, "values": [{"column": c, "value": v, "printed": str(v), "page": page,
                                            "status": "확인 필요" if flagged else "검사 통과"} for c, v in values]}

    def check(self, rows, **kwargs):
        return pc.check(self.registered, self.document, self.report(rows), **kwargs)


class PositionTests(Fixture):
    def in_order_rows(self):
        return [self.row("파생상품", [(0, 204), (1, 77)]), self.row("기타", [(0, None)]), self.row("파생상품", [(0, 54), (1, 20)]),
                self.row("기타", [(0, 100)]), self.row("충당부채", [(0, 300)]), self.row("충당부채", [(0, 400)], page=11)]

    def test_rows_in_print_order(self):
        totals = self.check(self.in_order_rows())["totals"]
        self.assertEqual((totals["places"], totals["in_order"], totals["S1_position"], totals["position_ready"]), (4, 4, 0, True))

    def test_swapped_rows_are_position_wrong(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)])]
        result = self.check(rows)
        self.assertEqual(result["totals"]["position_wrong"], 4)  # two rows, both periods
        self.assertEqual(result["totals"]["S1_position"], 4)

    def test_a_marked_swap_is_not_s1(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)], flagged=True), self.row("파생상품", [(0, 204), (1, 77)])]
        totals = self.check(rows)["totals"]
        self.assertEqual((totals["position_wrong"], totals["S1_position"]), (4, 2))

    def test_a_value_moved_into_a_dash_row(self):
        rows = self.in_order_rows()
        rows[1] = self.row("기타", [(0, 100)])
        rows[3] = self.row("기타", [(0, None)])
        place = next(p for p in self.check(rows)["places"] if "기타" in p["id"])
        self.assertEqual((place["status"], place["wrong_rows"]), ("position_wrong", [0]))

    def test_a_value_of_no_row_is_left_to_the_scorer(self):
        rows = self.in_order_rows()
        rows[0] = self.row("파생상품", [(0, 999), (1, 77)])
        result = self.check(rows)
        place = next(p for p in result["places"] if p["id"].endswith("파생상품|0"))
        self.assertEqual((place["wrong_rows"], place["scorer_wrong_unmarked"], place["added"]), ([0], 1, 0))
        self.assertEqual(result["totals"]["S1_position"], 0)

    def test_a_cell_the_scorer_counted_is_not_counted_twice(self):
        # 204 on both rows: the scorer pairs 204 with the first and counts the second "value wrong"
        rows = [self.row("파생상품", [(0, 204), (1, 77)]), self.row("파생상품", [(0, 204), (1, 20)])]
        place = next(p for p in self.check(rows)["places"] if p["id"].endswith("파생상품|0"))
        self.assertEqual((place["wrong_unmarked"], place["scorer_wrong_unmarked"], place["added"]), (1, 1, 0))

    def test_what_the_scorer_misses_is_added(self):
        # 54 moved up and 999 below: both rows are wrong, the scorer pairs 54 with the first row and counts only 999
        rows = [self.row("파생상품", [(0, 54), (1, 77)]), self.row("파생상품", [(0, 999), (1, 20)])]
        place = next(p for p in self.check(rows)["places"] if p["id"].endswith("파생상품|0"))
        self.assertEqual((place["wrong_unmarked"], place["scorer_wrong_unmarked"], place["added"]), (2, 1, 1))

    def test_the_scorer_s1_is_never_reduced(self):
        # a marked wrong row above, the right value unmarked below: the scorer counts the lower one, order says none
        rows = [self.row("파생상품", [(0, 54), (1, 77)], flagged=True), self.row("파생상품", [(0, 54), (1, 20)])]
        place = next(p for p in self.check(rows)["places"] if p["id"].endswith("파생상품|0"))
        self.assertEqual((place["wrong_unmarked"], place["scorer_wrong_unmarked"], place["added"]), (0, 1, 0))

    def test_rows_swapped_across_pages(self):
        # 10쪽 유동 "충당부채" and 11쪽 비유동 "충당부채": the scorer takes a cell of another page when its own page has none
        rows = self.in_order_rows()
        rows[4], rows[5] = self.row("충당부채", [(0, 400)]), self.row("충당부채", [(0, 300)], page=11)
        place = next(p for p in self.check(rows)["places"] if "충당부채" in p["id"])
        self.assertEqual((place["status"], place["wrong_rows"], place["pages"]), ("position_wrong", [0, 1], [10, 11]))

    def test_an_added_row_of_the_label(self):
        rows = self.in_order_rows() + [self.row("파생상품", [(0, 54), (1, 20)], page=11)]
        self.assertEqual({p["status"] for p in self.check(rows)["places"] if "파생상품" in p["id"]}, {"needs_verdict"})
        rows = self.in_order_rows() + [self.row("파생상품", [(0, 5), (1, 6)], page=11)]
        self.assertEqual({p["status"] for p in self.check(rows)["places"] if "파생상품" in p["id"]}, {"needs_verdict"})
        rows = self.in_order_rows() + [self.row("파생상품", [], page=11)]  # a row with no value is no row
        self.assertEqual(self.check(rows)["totals"]["in_order"], 4)

    def test_another_number_of_rows_needs_a_verdict_when_values_could_swap(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)]), self.row("파생상품", [(0, 5), (1, 6)])]
        result = self.check(rows)
        self.assertEqual(result["totals"]["needs_verdict"], 2)
        self.assertFalse(result["totals"]["position_ready"])

    def test_a_lost_row(self):
        # one row left: 54 may stand where 204 was printed (the scorer counts 54 correct, 204 missing)
        lost = [self.row("파생상품", [(0, 54), (1, 20)])]
        self.assertEqual({p["status"] for p in self.check(lost)["places"] if "파생상품" in p["id"]}, {"needs_verdict"})
        other = [self.row("파생상품", [(0, 5), (1, 6)])]  # no printed value of the place: nothing stands in a wrong row
        self.assertEqual({p["status"] for p in self.check(other)["places"] if "파생상품" in p["id"]}, {"not_pairable_no_swap"})

    def test_a_row_given_another_page_is_still_paired_by_order(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)], page=11)]
        self.assertEqual({p["status"] for p in self.check(rows)["places"] if "파생상품" in p["id"]}, {"position_wrong"})

    def test_equal_printed_values_cannot_swap(self):
        gold = json.loads((self.dir / "a.gold.json").read_text(encoding="utf-8"))
        for cell in gold["cells"]:
            if cell["label"] == "파생상품" and cell["period"] == 0:
                cell.update(printed="54", value=54)
        self.write_gold(gold)
        totals = self.check([self.row("파생상품", [(0, 54), (1, 20)])])["totals"]
        self.assertEqual(totals["needs_verdict"], 1)  # only period 1 (77 and 20 printed) waits

    def test_a_place_waiting_for_a_verdict_shows_the_scorer_result_of_each_row(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)]), self.row("파생상품", [(0, 5), (1, 6)])]
        place = next(p for p in self.check(rows)["places"] if p["id"].endswith("파생상품|0"))
        self.assertEqual([(r["row"], r["value"], r["scorer"]) for r in place["rows"]],
                         [(0, 54, "correct"), (1, 204, "correct"), (2, 5, "not_in_gold")])
        self.assertEqual(place["printed"], [204, 54])

    def test_verdicts(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)]), self.row("파생상품", [(0, 5), (1, 6)])]
        ids = [p["id"] for p in self.registered["documents"]["a"]["places"] if "파생상품" in p["id"]]
        verdicts = {"report_sha256": "r", "judged_by": "사용자",
                    "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": 2, "note": "10쪽 위 행에 아래 행 값"},
                                 ids[1]: {"verdict": "ok", "note": "전기는 순서대로"}}}
        totals = self.check(rows, verdicts=verdicts, report_sha256="r")["totals"]
        self.assertEqual((totals["S1_position"], totals["needs_verdict"], totals["position_ready"]), (2, 0, True))
        for broken in ({**verdicts, "report_sha256": "other"}, {k: v for k, v in verdicts.items() if k != "judged_by"},
                       {**verdicts, "verdicts": {**verdicts["verdicts"], "x|y|0": {"verdict": "ok", "note": "n"}}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "maybe", "note": "n"}}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": -1, "note": "n"}}},
                       # 3 > the two unmarked cells the scorer scored correct (the third row is outside the gold: 4.5)
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": 3, "note": "n"}}},
                       # Codex seventh re-check 2: "wrong" without its count, "ok" with one, not an object, no note
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "wrong", "note": "두 행이 바뀌었다"}}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": True, "note": "n"}}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": "2", "note": "n"}}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "ok", "wrong_unmarked": 1, "note": "n"}}},
                       {**verdicts, "verdicts": {ids[0]: "wrong"}},
                       {**verdicts, "verdicts": {ids[0]: {"verdict": "ok", "note": "  "}}},
                       {**verdicts, "verdicts": ["wrong"]}):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    self.check(rows, verdicts=broken, report_sha256="r")

    def test_a_verdicts_file_with_no_verdict_still_names_its_report(self):
        rows = self.in_order_rows()
        for broken in ({}, {"verdicts": {}}, {"report_sha256": "other", "judged_by": "사용자", "verdicts": {}},
                       {"report_sha256": "r", "judged_by": "", "verdicts": {}}):
            with self.subTest(broken=broken):
                with self.assertRaises(ValueError):
                    self.check(rows, verdicts=broken, report_sha256="r")
        empty = {"report_sha256": "r", "judged_by": "사용자", "verdicts": {}}
        self.assertTrue(self.check(rows, verdicts=empty, report_sha256="r")["totals"]["position_ready"])

    def test_an_explicit_zero_and_an_ok_with_zero_are_taken(self):
        rows = [self.row("파생상품", [(0, 54), (1, 20)], flagged=True), self.row("파생상품", [(0, 204), (1, 77)], flagged=True),
                self.row("파생상품", [(0, 5), (1, 6)])]
        ids = [p["id"] for p in self.registered["documents"]["a"]["places"] if "파생상품" in p["id"]]
        verdicts = {"report_sha256": "r", "judged_by": "사용자",
                    "verdicts": {ids[0]: {"verdict": "wrong", "wrong_unmarked": 0, "note": "바뀐 두 칸 모두 확인 필요 표시"},
                                 ids[1]: {"verdict": "ok", "wrong_unmarked": 0, "note": "전기는 순서대로"}}}
        totals = self.check(rows, verdicts=verdicts, report_sha256="r")["totals"]
        self.assertEqual((totals["S1_position"], totals["position_ready"]), (0, True))

    def test_registered_places_that_do_not_fit_the_gold_refuse_the_check(self):
        # Codex seventh re-check 3: a mapping changed after the places were built
        rows = [self.row("파생상품", [(0, 54), (1, 20)]), self.row("파생상품", [(0, 204), (1, 77)])]
        places = self.registered["documents"]["a"]["places"]
        broken = {"no places": [],
                  "a place missing": places[1:],
                  "a place added": places + [{**places[0], "id": "연결재무상태표@10|없음|0"}],
                  "a value changed": [{**places[0], "rows": [{**places[0]["rows"][0], "value": 999}] + places[0]["rows"][1:]}]
                                     + places[1:],
                  "a page changed": [{**places[0], "rows": [{**places[0]["rows"][0], "page": 11}] + places[0]["rows"][1:]}]
                                    + places[1:],
                  "a place twice": places + [places[0]]}
        for name, changed in broken.items():
            with self.subTest(name):
                registered = {"documents": {"a": {"pdf_sha256": "src", "places": changed}}}
                with self.assertRaises(ValueError):
                    pc.check(registered, self.document, self.report(rows))
        with self.assertRaises(ValueError):
            pc.check({"documents": {}}, self.document, self.report(rows))

    def test_statement_found_as_the_scorer_finds_it(self):
        result = pc.check(self.registered, self.document, self.report(self.in_order_rows(), title="재무상태표"))
        self.assertEqual({p["status"] for p in result["places"]}, {"statement_not_found"})

    def test_a_report_of_another_pdf_is_refused(self):
        report = self.report(self.in_order_rows(), source="other")
        with self.assertRaises(ValueError):
            pc.check(self.registered, self.document, report)

    def test_scan_pages(self):
        page_map = {"source_sha256": "src", "pages": [10, 11], "condition": "tilt", "scan_sha256": "scan", "scan": "a.tilt.pdf"}
        rows = [self.row("파생상품", [(0, 54), (1, 20)], page=1), self.row("파생상품", [(0, 204), (1, 77)], page=1),
                self.row("충당부채", [(0, 400)], page=1), self.row("충당부채", [(0, 300)], page=2)]
        report = self.report(rows, page=1, source="scan")
        result = pc.check(self.registered, self.document, report, page_map=page_map)
        self.assertEqual(result["totals"]["S1_position"], 6)


class BuildTests(unittest.TestCase):
    def save(self, folder, data):
        path = Path(folder) / f"registered{len(list(Path(folder).glob('registered*')))}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def line(self, page, top, *texts):
        return {"page": page, "words": [{"text": t, "top": top, "x0": n * 10} for n, t in enumerate(texts)]}

    def test_print_order_and_columns_counted_from_the_right(self):
        cells = [gold_cell("확정계약자산", 0, "7", 7, page=11), gold_cell("확정계약자산", 0, "54", 54),
                 gold_cell("확정계약자산", 0, "204", 204)]
        gold = {"source": {"file": "a.pdf", "sha256": "src", "pages": 20}, "statements": [STATEMENT], "cells": cells, "needs_mapping": []}
        lines = [self.line(10, 100, "확정계약자산", "9", "204", "77"), self.line(10, 200, "확정계약자산", "54", "20"),
                 self.line(11, 50, "확정계약자산", "7", "8")]
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(pc, "ROOT", Path(temp)):
            # a repository of its own: D5's list at its place, its freeze record with N = 1 (Codex D5 re-check 1-2)
            from document_list import profile_record
            for name, data in (("a.gold.json", gold), ("a.mapping.json", {"status": "draft", "decisions": {}})):
                (Path(temp) / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            scans = {c: {"pdf": f"a.{c}.pdf", "sha256": f"scan-{c}", "map": f"maps/a.{c}.map.json"} for c in ("normal", "tilt", "blur")}
            documents = {"expected_documents": 1, "documents": [{"key": "a", "rank": 1, "corp_code": "00000001", "pdf": "a.pdf",
                                                                  "sha256": "src", "gold": "a.gold.json",
                                                                  "mapping": "a.mapping.json", "scans": scans}]}
            with mock.patch("d4_gold.lines_of", return_value=lines):
                built = pc.build(documents, Path(temp))
            rows = built["documents"]["a"]["places"][0]["rows"]
            self.assertEqual([(r["page"], r["printed"]) for r in rows], [(10, "204"), (10, "54"), (11, "7")])
            listed = Path(temp) / "eval" / "d5_eval" / "documents.json"
            listed.parent.mkdir(parents=True)
            listed.write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")
            (Path(temp) / "eval" / "freeze_d5.json").write_text(json.dumps({"profile": profile_record("d5", 1)}),
                                                                 encoding="utf-8")
            with mock.patch("d4_gold.lines_of", return_value=lines), mock.patch.object(pc, "DOCUMENTS", listed):
                self.assertEqual(pc.main(["verify", "--pdf-dir", temp, "--registered", self.save(temp, built)]), 0)
                other = {**built, "documents": {"a": {**built["documents"]["a"], "places": []}}}
                self.assertEqual(pc.main(["verify", "--pdf-dir", temp, "--registered", self.save(temp, other)]), 1)
                # without --registered: the places of the list's evaluation
                (listed.parent / "duplicate_places.json").write_text(json.dumps(built), encoding="utf-8")
                self.assertEqual(pc.main(["verify", "--pdf-dir", temp]), 0)
                # a list at no evaluation's place has no N from outside it
                (Path(temp) / "documents.json").write_text(json.dumps(documents, ensure_ascii=False), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    pc.main(["verify", "--pdf-dir", temp, "--documents", str(Path(temp) / "documents.json")])
            lines[1] = self.line(10, 200, "확정계약자산", "55", "20")
            with mock.patch("d4_gold.lines_of", return_value=lines):
                with self.assertRaises(ValueError):
                    pc.build(documents, Path(temp))


class RegisteredTests(unittest.TestCase):
    def test_registered_places_match_the_golds(self):
        registered = json.loads((ROOT / "eval/d4_eval/duplicate_places.json").read_text(encoding="utf-8"))
        documents = json.loads(pc.DOCUMENTS.read_text(encoding="utf-8"))["documents"]
        self.assertEqual(sorted(registered["documents"]), sorted(d["key"] for d in documents))
        for document in documents:
            gold = pc._gold_for(document, None)
            places = pc.places_of(gold)
            entry = registered["documents"][document["key"]]
            self.assertEqual(entry["pdf_sha256"], document["sha256"])
            self.assertEqual(sorted(p["id"] for p in entry["places"]), sorted(pc.place_id(*k) for k in places))
            for place in entry["places"]:
                group = places[(place["statement_id"], place["key"], place["period"])]
                self.assertEqual(sorted(map(str, (r["value"] for r in place["rows"]))), sorted(map(str, (c["value"] for c in group))))
                order = [(r["page"], r["top"]) for r in place["rows"]]
                self.assertEqual(order, sorted(order))

    def test_a_real_report_with_two_rows_swapped(self):
        # a saved development report (its gold and places from the gold's order): swap the values of one place
        dev = ROOT / "eval/documents_2026-10-11_after-fourth"
        document = {"key": "naver", "sha256": None, "gold": str(dev / "d4_dev/naver.gold.json"),
                    "mapping": str(dev / "d4_dev/naver.mapping.json")}
        gold = pc._gold_for(document, None)
        document["sha256"] = gold["source"]["sha256"]
        places = gold_order(gold)
        registered = {"documents": {"naver": {"pdf_sha256": document["sha256"], "places": places}}}
        report = json.loads((dev / "reports/naver.ai.report.json").read_text(encoding="utf-8"))
        self.assertEqual(pc.check(registered, document, report)["totals"]["position_wrong"], 0)
        place = next(p for p in places if len({r["value"] for r in p["rows"]}) == len(p["rows"]) and None not in [r["value"] for r in p["rows"]])
        swapped = copy.deepcopy(report)
        hits = [v for s in swapped["statements"] for row in s["rows"] if pc.label_key(row["label"]) == place["key"]
                for v in row["values"] if v["column"] == place["period"]]
        hits[0]["value"], hits[1]["value"] = hits[1]["value"], hits[0]["value"]
        self.assertGreaterEqual(pc.check(registered, document, swapped)["totals"]["position_wrong"], 2)
        self.assertEqual(pc.check(registered, document, report)["totals"]["S1_position"], 0)


if __name__ == "__main__":
    unittest.main()
