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


class Fixture(unittest.TestCase):
    """One document (a balance sheet printing "파생상품" on two rows), its text PDF and three scans, and a run folder
    of the AI reader whose four calls exited 0."""

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
        self.document = {"key": "a", "rank": 1, "corp_code": "00000001", "pdf": "a.pdf", "company": "가", "sha256": "src",
                         "gold": str(self.dir / "a.gold.json"),
                         "mapping": str(self.dir / "a.mapping.json"), "scans": scans}
        self.documents = {"expected_documents": 1, "documents": [self.document]}
        applied = apply_mapping(gold, mapping)
        places = [{"id": pc.place_id(*k), "statement_id": k[0], "key": k[1], "period": k[2],
                   "rows": [{"page": c["page"], "top": n, "label": c["label"], "printed": c["printed"], "value": c["value"]}
                            for n, c in enumerate(v)]}
                  for k, v in pc.places_of(applied).items()]
        self.registered = {"documents": {"a": {"pdf_sha256": "src", "places": places}}}
        self.run = self.dir / "run"
        (self.run / "reports").mkdir(parents=True)
        self.names = [f"a.{variant}.ai" for variant in ("text", "normal", "tilt", "blur")]
        self.write_run()
        self.judgments = self.dir / "judgments"
        self.judgments.mkdir()

    def write_run(self, exits=None, finished=True, preflight=True, readers=("ai",), log=None):
        """run.json and run_log.jsonl as eval/d4_eval/run_d4.py writes them (every call exits 0 unless ``exits``)."""
        exits = exits or {}
        names = [n.replace(".ai", f".{r}") for r in readers for n in self.names]
        failed = [{"name": n, "exit": exits[n]} for n in names if exits.get(n, 0) != 0]
        record = {"commit": "R", "readers": list(readers), "calls": len(names), "started_at": "t",
                  "documents_sha256": official_d4._sha256(official_d4.DOCUMENTS),
                  "preflight": {"log": "run1.preflight.json", "sha256": "p", "checked_at": "t"} if preflight else None}
        if finished:
            record |= {"finished_at": "t", "succeeded": len(names) - len(failed), "failed": failed}
        (self.run / "run.json").write_text(json.dumps(record), encoding="utf-8")
        lines = log if log is not None else [{"n": i, "name": n, "exit": exits.get(n, 0)} for i, n in enumerate(names, 1)]
        (self.run / "run_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")

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
        return official_d4.official(self.run, self.judgments, self.documents, self.registered)


class OfficialTests(Fixture):
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


class RunGateTests(Fixture):
    """Codex seventh re-check 1: a report a failed call left behind is never official."""

    def setUp(self):
        super().setUp()
        self.save("a.text.ai", PRINTED)  # scored right: only the run's record can keep it from "met"

    def verdict(self):
        return self.result()["readers"]["ai"]["3.1"]["verdict"]

    def test_a_right_report_of_a_call_that_exited_0_is_met(self):
        self.assertEqual(self.verdict(), "met")

    def test_a_report_left_by_a_failed_call_is_not_official(self):
        self.write_run(exits={"a.text.ai": 2})
        call = self.result()["calls"][0]
        self.assertFalse(call["official_ready"])
        self.assertIn("exited 2", call["why"])
        self.assertIn("lists the call as failed", call["why"])
        self.assertEqual(call["S1_official"], 0)  # the numbers stay, as provisional
        self.assertEqual(self.verdict(), "not official")

    def test_the_run_record_must_be_whole(self):
        logged = [{"n": i, "name": n, "exit": 0} for i, n in enumerate(self.names, 1)]
        cases = {"not finished": dict(finished=False), "no preflight": dict(preflight=False),
                 "no log entry": dict(log=logged[1:]), "two log entries": dict(log=logged + logged[:1]),
                 "a log entry without exit": dict(log=[{"n": 1, "name": "a.text.ai"}] + logged[1:])}
        for name, kwargs in cases.items():
            with self.subTest(name):
                self.write_run(**kwargs)
                self.assertEqual(self.verdict(), "not official")

    def test_counts_that_do_not_add_up(self):
        record = json.loads((self.run / "run.json").read_text(encoding="utf-8"))
        for changed in ({**record, "succeeded": 3}, {**record, "calls": 5}, {**record, "failed": "none"},
                        {**record, "documents_sha256": "other"}):
            with self.subTest(changed=changed):
                (self.run / "run.json").write_text(json.dumps(changed), encoding="utf-8")
                self.assertEqual(self.verdict(), "not official")

    def test_a_record_that_does_not_agree_with_itself(self):
        # Codex eighth review 1: calls nobody planned, or a failed list of other calls, keep the whole folder out
        logged = [{"n": i, "name": n, "exit": 0} for i, n in enumerate(self.names, 1)]
        record = json.loads((self.run / "run.json").read_text(encoding="utf-8"))
        cases = {
            "a foreign log line": (record, logged + [{"n": 5, "name": "foreign.text.ai", "exit": 0}]),
            "a foreign failed call": ({**record, "succeeded": 3, "failed": [{"name": "foreign.text.ai", "exit": 2}]}, logged),
            "a failed call listed twice": ({**record, "succeeded": 2, "failed": [{"name": "a.tilt.ai", "exit": 1}] * 2},
                                           logged[:2] + [{**logged[2], "exit": 1}] + logged[3:]),
            "a failed exit the log does not have": ({**record, "succeeded": 3, "failed": [{"name": "a.tilt.ai", "exit": 1}]},
                                                    logged[:2] + [{**logged[2], "exit": 2}] + logged[3:]),
            "a logged failure run.json does not list": (record, logged[:2] + [{**logged[2], "exit": 1}] + logged[3:]),
            "the log out of order": (record, [logged[1], logged[0]] + logged[2:]),
            "numbers out of order": (record, [{**logged[0], "n": 2}, {**logged[1], "n": 1}] + logged[2:]),
            "an exit that is not a number": (record, [{**logged[0], "exit": False}] + logged[1:]),
            "readers out of order": ({**record, "readers": ["ai", "rules"]}, logged),
            "a reader twice": ({**record, "readers": ["ai", "ai"]}, logged),
            "a log line that is not an object": (record, logged[:3] + [["a.blur.ai", 0]]),
        }
        for name, (changed, lines) in cases.items():
            with self.subTest(name):
                (self.run / "run.json").write_text(json.dumps(changed), encoding="utf-8")
                (self.run / "run_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
                self.assertEqual(self.verdict(), "not official")
                self.assertFalse(self.result()["calls"][0]["official_ready"])

    def test_a_failed_call_of_the_other_reader_keeps_this_reader_official(self):
        self.write_run(readers=("rules", "ai"), exits={"a.blur.rules": 3})
        (self.run / "reports" / "a.text.rules.json").write_bytes((self.run / "reports" / "a.text.ai.json").read_bytes())
        result = self.result()
        self.assertEqual(result["readers"]["ai"]["3.1"]["verdict"], "met")
        self.assertEqual(result["readers"]["rules"]["3.1"]["verdict"], "met")
        self.assertEqual(result["readers"]["rules"]["3.3"]["verdict"], "not official")

    def test_a_log_that_cannot_be_read(self):
        (self.run / "run_log.jsonl").write_text("{not json\n", encoding="utf-8")
        self.assertEqual(self.verdict(), "not official")

    def test_one_reader_of_a_folder(self):
        # rules from this folder; the AI reader ran again elsewhere after a model server failure
        self.write_run(readers=("rules", "ai"), exits={"a.text.ai": 1})
        (self.run / "reports" / "a.text.rules.json").write_bytes((self.run / "reports" / "a.text.ai.json").read_bytes())
        result = official_d4.official(self.run, self.judgments, self.documents, self.registered, ["rules"])
        self.assertEqual(list(result["readers"]), ["rules"])
        self.assertEqual(result["readers"]["rules"]["3.1"]["verdict"], "met")
        with self.assertRaises(ValueError):
            official_d4.official(self.run, self.judgments, self.documents, self.registered, ["other"])

    def test_judgment_files_of_another_shape_are_refused(self):
        # Codex eighth review 2: an empty list, string, or false is not "no verdicts"
        # Codex ninth review 1: a file of "null" is a file, not "no file"
        for content in ("[]", '{"verdicts": ["wrong"]}', '{"verdicts": {"0/3/0": "wrong"}}', '{"verdicts": []}',
                        '{"verdicts": ""}', '{"verdicts": false}', '{"verdicts": null}', "not json", "null"):
            with self.subTest(content=content):
                (self.judgments / "a.text.ai.extras.json").write_text(content, encoding="utf-8")
                call = self.result()["calls"][0]
                self.assertFalse(call["official_ready"])
                self.assertIn("refused", call["why"])
        (self.judgments / "a.text.ai.extras.json").unlink()
        for content in ("[]", '{"verdicts": ["x"]}', '{"verdicts": []}', '{"verdicts": ""}', '{"verdicts": false}',
                        '{"verdicts": null}', "not json", "null"):
            with self.subTest(content=content):
                (self.judgments / "a.text.ai.position.json").write_text(content, encoding="utf-8")
                self.assertIn("refused", self.result()["calls"][0]["why"])
        (self.judgments / "a.text.ai.position.json").unlink()
        report_sha = sha((self.run / "reports" / "a.text.ai.json").read_bytes())
        empty = {"report_sha256": report_sha, "judged_by": "사용자", "verdicts": {}}
        for name in ("a.text.ai.extras.json", "a.text.ai.position.json"):
            # Codex ninth review 3: a file with no verdict still names this report and who judged
            for broken in ({"verdicts": {}}, {**empty, "report_sha256": "other"}, {**empty, "judged_by": " "}, {}):
                with self.subTest(name, broken=broken):
                    (self.judgments / name).write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
                    self.assertEqual(self.verdict(), "not official")
            with self.subTest(name, empty=True):
                (self.judgments / name).write_text(json.dumps(empty, ensure_ascii=False), encoding="utf-8")
                self.assertEqual(self.verdict(), "met")
            (self.judgments / name).unlink()

    def test_a_report_that_is_not_json_is_refused(self):
        (self.run / "reports" / "a.text.ai.json").write_text("{cut off", encoding="utf-8")
        self.assertIn("refused", self.result()["calls"][0]["why"])
        (self.run / "reports" / "a.text.ai.json").write_text("[]", encoding="utf-8")
        self.assertIn("refused", self.result()["calls"][0]["why"])

    def test_misnamed_judgment_files_are_listed_and_not_read(self):
        (self.judgments / "a.text.ai.extra.json").write_text("{}", encoding="utf-8")
        # Codex ninth review 2: another reader's file is not read by this aggregation either
        (self.judgments / "a.text.rules.extras.json").write_text("{}", encoding="utf-8")
        result = self.result()
        self.assertEqual(result["judgment_files_not_read"], ["a.text.ai.extra.json", "a.text.rules.extras.json"])
        self.assertEqual(self.verdict(), "met")

    def test_a_reader_named_twice_is_counted_once(self):
        result = official_d4.official(self.run, self.judgments, self.documents, self.registered, ["ai", "ai"])
        self.assertEqual(result["readers"]["ai"]["3.1"]["calls"], 1)
        self.assertEqual(len(result["calls"]), 4)

    def test_a_wrong_verdict_without_its_count_does_not_make_a_swap_met(self):
        # Codex seventh re-check 2: two rows swapped and an empty row of the label added
        report_sha = self.save("a.text.ai", [PRINTED[2], PRINTED[1], PRINTED[0], ("파생상품", 5, 6)])
        ids = [p["id"] for p in self.result()["calls"][0]["position_places"]]
        verdicts = {"report_sha256": report_sha, "judged_by": "사용자",
                    "verdicts": {i: {"verdict": "wrong", "note": "두 금액의 인쇄 행이 바뀌었다"} for i in ids}}
        (self.judgments / "a.text.ai.position.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.verdict(), "not official")
        verdicts["verdicts"] = {i: {"verdict": "wrong", "wrong_unmarked": 2, "note": "두 금액의 인쇄 행이 바뀌었다"} for i in ids}
        (self.judgments / "a.text.ai.position.json").write_text(json.dumps(verdicts, ensure_ascii=False), encoding="utf-8")
        extras = {"report_sha256": report_sha, "judged_by": "사용자",
                  "verdicts": {"0/3/0": {"verdict": "wrong", "note": "인쇄되지 않은 행"},
                               "0/3/1": {"verdict": "wrong", "note": "인쇄되지 않은 행, 전기"}}}
        (self.judgments / "a.text.ai.extras.json").write_text(json.dumps(extras, ensure_ascii=False), encoding="utf-8")
        call = self.result()["calls"][0]
        self.assertEqual((call["official_ready"], call["S1"], call["S1_position"]), (True, 2, 4))
        self.assertEqual(self.verdict(), "not met")

    def test_registered_places_that_do_not_fit_refuse_the_call(self):
        # Codex seventh re-check 3: an empty list of places and two rows swapped
        self.registered["documents"]["a"]["places"] = []
        self.save("a.text.ai", [PRINTED[2], PRINTED[1], PRINTED[0]])
        call = self.result()["calls"][0]
        self.assertIn("do not fit the gold", call["why"])
        self.assertEqual(self.verdict(), "not official")


if __name__ == "__main__":
    unittest.main()
