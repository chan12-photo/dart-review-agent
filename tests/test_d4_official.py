"""The D4 official result (eval/d4_eval/official_d4.py): scorer + position check + verdicts, per reader and bundle."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

import official_d4  # noqa: E402
import position_check as pc  # noqa: E402
from eval.d4_gold import apply_mapping  # noqa: E402

STATEMENT = {"id": "연결재무상태표@10", "kind": "BS", "title": "연결재무상태표", "consolidated": True, "page": 10,
             "end_page": 10, "unit_text": "원"}
PRINTED = [("파생상품", 204, 77), ("유동자산", 900, 800), ("파생상품", 54, 20)]  # print order, top to bottom


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class OfficialTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        cells = [{"statement_id": STATEMENT["id"], "statement": STATEMENT["title"], "kind": "BS", "page": 10, "label": label,
                  "period": period, "printed": f"{value:,}", "value": value}
                 for label, current, prior in PRINTED for period, value in ((0, current), (1, prior))]
        gold = {"source": {"file": "a.pdf", "sha256": "src", "pages": 20}, "statements": [STATEMENT], "cells": cells,
                "needs_mapping": []}
        mapping = {"status": "confirmed", "confirmed_by": "t", "confirmed_at": "t", "decisions": {}}
        for name, data in (("a.gold.json", gold), ("a.mapping.json", mapping)):
            (self.dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        scans = {}
        for condition in ("normal", "tilt", "blur"):
            page_map = {"source_sha256": "src", "pages": [10], "condition": condition, "scan_sha256": f"scan-{condition}",
                        "scan": f"a.{condition}.pdf"}
            (self.dir / f"{condition}.map.json").write_text(json.dumps(page_map), encoding="utf-8")
            scans[condition] = {"pdf": f"a.{condition}.pdf", "sha256": f"scan-{condition}", "map": str(self.dir / f"{condition}.map.json")}
        self.document = {"key": "a", "company": "가", "sha256": "src", "gold": str(self.dir / "a.gold.json"),
                         "mapping": str(self.dir / "a.mapping.json"), "scans": scans}
        applied = apply_mapping(gold, mapping)
        places = [{"id": pc.place_id(*k), "statement_id": k[0], "key": k[1], "period": k[2],
                   "rows": [{"page": c["page"], "top": n, "label": c["label"], "printed": c["printed"], "value": c["value"]}
                            for n, c in enumerate(v)]}
                  for k, v in pc.places_of(applied).items()]
        self.registered = {"documents": {"a": {"pdf_sha256": "src", "places": places}}}
        self.run = self.dir / "run"
        (self.run / "reports").mkdir(parents=True)
        (self.run / "run.json").write_text(json.dumps({"commit": "R", "readers": ["ai"], "calls": 4, "failed": []}), encoding="utf-8")
        self.judgments = self.dir / "judgments"
        self.judgments.mkdir()

    def save(self, name, rows, source="src", page=10):
        values = lambda current, prior, flagged=False: [
            {"column": c, "value": v, "printed": f"{v:,}", "page": page, "status": "확인 필요" if flagged else "검사 통과"}
            for c, v in ((0, current), (1, prior))]
        report = {"source_sha256": source, "problems": [], "statements": [
            {"title": STATEMENT["title"], "page": page, "problems": [], "sums_checked": 2, "sums_uncertain": False,
             "rows": [{"label": label, "values": values(*numbers)} for label, *numbers in rows]}]}
        path = self.run / "reports" / f"{name}.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return sha(path.read_bytes())

    def result(self):
        return official_d4.official(self.run, self.judgments, {"documents": [self.document]}, self.registered)

    def test_rows_in_print_order_meet_the_text_criterion_and_missing_scans_are_not_official(self):
        self.save("a.text.ai", PRINTED)
        result = self.result()["readers"]["ai"]
        self.assertEqual((result["3.1"]["verdict"], result["3.1"]["sums"]["correct"]), ("met", 6))
        self.assertEqual(result["3.3"]["verdict"], "not official")
        self.assertEqual(len(result["3.3"]["not_official"]), 3)

    def test_swapped_rows_the_scorer_counts_correct_fail_the_criterion(self):
        # Codex seventh review 1, end to end: the scorer alone gives S1 = 0
        self.save("a.text.ai", [PRINTED[2], PRINTED[1], PRINTED[0]])
        call = self.result()["calls"][0]
        self.assertEqual((call["S1"], call["S1_position"], call["S1_official"]), (0, 4, 4))
        self.assertEqual(self.result()["readers"]["ai"]["3.1"]["verdict"], "not met")

    def test_a_cell_outside_the_gold_waits_for_a_verdict_then_counts(self):
        report_sha = self.save("a.text.ai", PRINTED + [("기타", 5, 6)])
        part = self.result()["readers"]["ai"]["3.1"]
        self.assertEqual(part["verdict"], "not official")
        self.assertIn("extras_judged", part["not_official"][0]["why"])
        self.assertEqual([x["id"] for x in self.result()["calls"][0]["extras_to_judge"]], ["0/3/0", "0/3/1"])
        verdicts = {"report_sha256": report_sha, "judged_by": "사용자",
                    "verdicts": {"0/3/0": {"verdict": "wrong", "note": "인쇄본에 없는 행"},
                                 "0/3/1": {"verdict": "wrong", "note": "인쇄본에 없는 행, 전기"}}}
        (self.judgments / "a.text.ai.extras.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        part = self.result()["readers"]["ai"]["3.1"]
        self.assertEqual((part["verdict"], part["sums"]["S1_official"], part["sums"]["extras_judged"]), ("not met", 2, 2))

    def test_verdicts_of_another_report_are_refused(self):
        self.save("a.text.ai", PRINTED + [("기타", 5, 6)])
        verdicts = {"report_sha256": "other", "judged_by": "사용자", "verdicts": {"0/3/0": {"verdict": "ok", "note": "n"}}}
        (self.judgments / "a.text.ai.extras.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        call = self.result()["calls"][0]
        self.assertFalse(call["official_ready"])
        self.assertIn("refused", call["why"])

    def test_scans_are_scored_on_their_own_pages(self):
        self.save("a.text.ai", PRINTED)
        for condition in ("normal", "tilt", "blur"):
            self.save(f"a.{condition}.ai", PRINTED, source=f"scan-{condition}", page=1)
        result = self.result()["readers"]["ai"]
        self.assertEqual((result["3.3"]["verdict"], result["3.3"]["sums"]["correct"]), ("met", 18))
        self.save("a.blur.ai", [PRINTED[2], PRINTED[1], PRINTED[0]], source="scan-blur", page=1)
        self.assertEqual(self.result()["readers"]["ai"]["3.3"]["verdict"], "not met")

    def test_a_lost_row_waits_for_a_position_verdict(self):
        report_sha = self.save("a.text.ai", PRINTED[1:])
        call = self.result()["calls"][0]
        self.assertEqual((call["S2"], call["needs_verdict"], call["official_ready"]), (2, 2, False))
        ids = [p["id"] for p in call["position_places"]]
        verdicts = {"report_sha256": report_sha, "judged_by": "사용자",
                    "verdicts": {i: {"verdict": "ok", "note": "남은 행은 비유동 자리(유동자산 아래)"} for i in ids}}
        (self.judgments / "a.text.ai.position.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        part = self.result()["readers"]["ai"]["3.1"]
        self.assertEqual((part["verdict"], part["sums"]["S2"]), ("not met", 2))


if __name__ == "__main__":
    unittest.main()
