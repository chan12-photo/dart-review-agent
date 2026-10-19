"""The D4 official runner's plan: order, input checks, and folders (nothing is run)."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "d4_eval"))

import run_d4  # noqa: E402


class PlanTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.dir = Path(temp.name)
        (self.dir / "scans").mkdir()
        self.documents = {"documents": []}
        for key in ("01_a", "02_b"):
            pdf = self.dir / f"{key}.pdf"
            pdf.write_bytes(f"pdf {key}".encode())
            scans = {}
            for condition in run_d4.CONDITIONS:
                scan = self.dir / "scans" / f"{key}.{condition}.pdf"
                scan.write_bytes(f"scan {key} {condition}".encode())
                scans[condition] = {"pdf": scan.name, "sha256": hashlib.sha256(scan.read_bytes()).hexdigest(),
                                    "map": f"maps/{key}.{condition}.map.json"}
            self.documents["documents"].append({"key": key, "pdf": pdf.name, "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                                                "gold": f"g/{key}.gold.json", "mapping": f"g/{key}.mapping.json", "scans": scans})

    def plan(self, readers=run_d4.READERS):
        return run_d4.plan(self.documents, self.dir, self.dir / "scans", self.dir / "run", readers)

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


if __name__ == "__main__":
    unittest.main()
