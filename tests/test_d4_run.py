"""The D4 official runner: its plan (order, input checks, folders) and its run with fake scorer calls."""

import hashlib
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "d4_eval"))

import run_d4  # noqa: E402


class Inputs(unittest.TestCase):
    """Two documents, each a text PDF and three scans, with their SHA-256 in a document list."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        (self.dir / "scans").mkdir()
        self.documents = {"expected_documents": 2, "documents": []}
        for key in ("01_a", "02_b"):
            pdf = self.dir / f"{key}.pdf"
            pdf.write_bytes(f"pdf {key}".encode())
            scans = {}
            for condition in run_d4.CONDITIONS:
                scan = self.dir / "scans" / f"{key}.{condition}.pdf"
                scan.write_bytes(f"scan {key} {condition}".encode())
                scans[condition] = {"pdf": scan.name, "sha256": hashlib.sha256(scan.read_bytes()).hexdigest(),
                                    "map": f"maps/{key}.{condition}.map.json"}
            self.documents["documents"].append({"key": key, "rank": int(key[:2]), "corp_code": f"0000000{key[1]}", "pdf": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                                "gold": f"g/{key}.gold.json", "mapping": f"g/{key}.mapping.json", "scans": scans})

    def plan(self, readers=run_d4.READERS):
        return run_d4.plan(self.documents, self.dir, self.dir / "scans", self.dir / "run", readers)


class PlanTests(Inputs):
    def test_rules_first_then_ai_each_document_text_then_scans(self):
        names = [call["name"] for call in self.plan()]
        self.assertEqual(len(names), 16)
        self.assertEqual(names[:4], ["01_a.text.rules", "01_a.normal.rules", "01_a.tilt.rules", "01_a.blur.rules"])
        self.assertEqual(names[8], "01_a.text.ai")
        self.assertTrue(all(name.endswith(".rules") for name in names[:8]))

    def test_scans_get_their_page_map_and_text_does_not(self):
        calls = {call["name"]: call["command"] for call in self.plan()}
        self.assertNotIn("--page-map", calls["01_a.text.rules"])
        tilt = calls["01_a.tilt.ai"]
        self.assertEqual(tilt[tilt.index("--page-map") + 1], str(ROOT / "maps/01_a.tilt.map.json"))
        self.assertEqual(tilt[tilt.index("--reader") + 1], "ai")
        self.assertEqual(tilt[-2:], ["--out", str(self.dir / "run" / "scores" / "01_a.tilt.ai.json")])

    def test_other_bytes_or_missing_files_are_refused(self):
        (self.dir / "scans" / "02_b.blur.pdf").write_bytes(b"changed")
        with self.assertRaises(ValueError) as caught:
            self.plan()
        self.assertIn("02_b blur", str(caught.exception))
        (self.dir / "01_a.pdf").unlink()
        with self.assertRaises(ValueError):
            self.plan()

    def test_one_reader_again(self):
        self.assertTrue(all(call["reader"] == "ai" for call in self.plan(("ai",))))

    def test_an_existing_run_folder_is_never_reused(self):
        existing = self.dir / "used"
        existing.mkdir()
        with self.assertRaises(SystemExit):
            run_d4.main(["--pdf-dir", str(self.dir), "--scan-dir", str(self.dir), "--out", str(existing), "--dry-run"])

    def test_the_registered_document_list_is_complete(self):
        documents = json.loads(run_d4.DOCUMENTS.read_text(encoding="utf-8"))["documents"]
        self.assertEqual(len(documents), 10)
        for document in documents:
            self.assertTrue((ROOT / document["gold"]).exists() and (ROOT / document["mapping"]).exists())
            self.assertEqual(sorted(document["scans"]), sorted(run_d4.CONDITIONS))
            for scan in document["scans"].values():
                page_map = json.loads((ROOT / scan["map"]).read_text(encoding="utf-8"))
                self.assertEqual((page_map["scan_sha256"], page_map["source_sha256"]), (scan["sha256"], document["sha256"]))


class RunTests(Inputs):
    """main() with the scorer calls and git faked: nothing of the product runs."""

    def setUp(self):
        super().setUp()
        documents = self.dir / "documents.json"
        documents.write_text(json.dumps(self.documents), encoding="utf-8")
        self.enterContext(mock.patch.object(run_d4, "DOCUMENTS", documents))
        self.status = ""
        self.enterContext(mock.patch.object(run_d4, "_git", side_effect=lambda *a: "abc" if a[0] == "rev-parse" else self.status))
        self.preflight = self.dir / "run.preflight.json"
        self.write_preflight()
        self.exits = {}
        self.called = []

        def fake(command, **kwargs):
            name = Path(command[command.index("--out") + 1]).stem
            self.called.append(name)
            return subprocess.CompletedProcess(command, self.exits.get(name, 0), "{}\n", "")
        self.enterContext(mock.patch.object(run_d4.subprocess, "run", side_effect=fake))

    def write_preflight(self, head="abc", ok=True):
        self.preflight.write_text(json.dumps({"head": head, "ok": ok, "checked_at": "t",
                                              "checks": [{"check": "clean", "ok": ok}]}), encoding="utf-8")

    def run_main(self, *extra):
        argv = ["--pdf-dir", str(self.dir), "--scan-dir", str(self.dir / "scans"), "--out", str(self.dir / "run"), *extra]
        return run_d4.main(argv)

    def run_json(self):
        return json.loads((self.dir / "run" / "run.json").read_text(encoding="utf-8"))

    def test_every_call_exits_0(self):
        self.assertEqual(self.run_main("--preflight", str(self.preflight)), 0)
        run = self.run_json()
        self.assertEqual((run["succeeded"], run["failed"], run["commit"]), (16, [], "abc"))
        self.assertEqual(run["preflight"]["sha256"], run_d4._sha256(self.preflight))

    def test_a_failed_call_is_recorded_the_run_goes_on_and_exits_1(self):
        self.exits = {"01_a.tilt.ai": 2, "02_b.text.rules": 1}
        self.assertEqual(self.run_main("--preflight", str(self.preflight)), 1)
        run = self.run_json()
        self.assertEqual(run["failed"], [{"name": "02_b.text.rules", "exit": 1}, {"name": "01_a.tilt.ai", "exit": 2}])
        self.assertEqual(run["succeeded"], 14)
        self.assertEqual(len(self.called), 16)
        log = (self.dir / "run" / "run_log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["exit"] for line in log].count(0), 14)

    def test_nothing_runs_without_a_passed_preflight_at_this_head(self):
        cases = {"none": (), "missing": ("--preflight", str(self.dir / "absent.json"))}
        for name, extra in cases.items():
            with self.subTest(name):
                self.assertEqual(self.run_main(*extra), 2)
        for head, ok in (("abc", False), ("other", True)):
            with self.subTest(head=head, ok=ok):
                self.write_preflight(head, ok)
                self.assertEqual(self.run_main("--preflight", str(self.preflight)), 2)
        self.assertFalse((self.dir / "run").exists())
        self.assertEqual(self.called, [])

    def test_nothing_runs_when_the_checkout_changed_after_the_preflight(self):
        self.status = "?? stray.txt"
        self.assertEqual(self.run_main("--preflight", str(self.preflight)), 2)
        self.assertFalse((self.dir / "run").exists())

    def test_logs_and_run_folders_inside_the_checkout_are_refused(self):
        with self.assertRaises(ValueError):
            run_d4.preflight_passed(ROOT / "eval" / "freeze_d4.json", "abc")
        with self.assertRaises(SystemExit):
            run_d4.main(["--pdf-dir", str(self.dir), "--scan-dir", str(self.dir / "scans"),
                         "--out", str(ROOT / "d4_run_never_created"), "--dry-run"])
        self.assertFalse((ROOT / "d4_run_never_created").exists())

    def test_readers_once_each_in_the_registered_order(self):
        for readers in (["ai", "ai"], ["ai", "rules"], ["rules", "rules", "ai"]):
            with self.subTest(readers=readers):
                with self.assertRaises(SystemExit):
                    self.run_main("--readers", *readers, "--preflight", str(self.preflight))
        self.assertEqual(self.called, [])
        self.assertEqual(self.run_main("--readers", "ai", "--preflight", str(self.preflight)), 0)
        self.assertEqual(self.run_json()["calls"], 8)

    def test_the_official_gate_reads_this_runner_s_record(self):
        # the record of an honest run (one call failed) lets every other call be official, and only those
        import official_d4
        self.exits = {"01_a.tilt.ai": 2}
        self.assertEqual(self.run_main("--preflight", str(self.preflight)), 1)
        names = [f"{d['key']}.{v}.{r}" for r in run_d4.READERS for d in self.documents["documents"] for v in official_d4.VARIANTS]
        with mock.patch.object(official_d4, "DOCUMENTS", run_d4.DOCUMENTS):
            gate = official_d4.run_gate(self.dir / "run", self.run_json(), names)
        self.assertEqual(len(gate), 16)
        self.assertEqual({name for name, why in gate.items() if why}, {"01_a.tilt.ai"})

    def test_the_official_gate_reads_a_rerun_of_one_reader(self):
        import official_d4
        self.assertEqual(self.run_main("--readers", "ai", "--preflight", str(self.preflight)), 0)
        names = [f"{d['key']}.{v}.ai" for d in self.documents["documents"] for v in official_d4.VARIANTS]
        with mock.patch.object(official_d4, "DOCUMENTS", run_d4.DOCUMENTS):
            gate = official_d4.run_gate(self.dir / "run", self.run_json(), names)
        self.assertEqual(set(gate.values()), {None})

    def test_a_document_list_given_on_the_command_line(self):
        # D5 runs the same runner on its own document list (D5 contract draft 3)
        other = self.dir / "d5_documents.json"
        other.write_text(json.dumps(self.documents) + "\n", encoding="utf-8")
        self.assertEqual(self.run_main("--documents", str(other), "--preflight", str(self.preflight)), 0)
        self.assertEqual(self.run_json()["documents_sha256"], run_d4._sha256(other))

    def test_a_dry_run_needs_no_preflight_and_writes_nothing(self):
        self.assertEqual(self.run_main("--dry-run"), 0)
        self.assertFalse((self.dir / "run").exists())
        self.assertEqual(self.called, [])


if __name__ == "__main__":
    unittest.main()
