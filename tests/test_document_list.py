"""The registered document list is complete and without repeats (eval/d4_eval/document_list.py, Codex D5 review 1)."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

from document_list import check_document_list, is_d4_list  # noqa: E402
import official_d4  # noqa: E402


def document(n):
    scans = {c: {"pdf": f"{n:02d}.{c}.pdf", "sha256": f"scan-{n}-{c}", "map": f"eval/d5_eval/scans/{n:02d}.{c}.map.json"}
             for c in ("normal", "tilt", "blur")}
    return {"key": f"{n:02d}_0000000{n}", "rank": 19 + n, "corp_code": f"0000000{n}", "pdf": f"{n:02d}.pdf",
            "sha256": f"text-{n}", "gold": f"eval/d5_eval/gold/{n:02d}.gold.json",
            "mapping": f"eval/d5_eval/gold/{n:02d}.mapping.json", "scans": scans}


def listing(count=3, expected=3):
    return {"expected_documents": expected, "documents": [document(n) for n in range(1, count + 1)]}


class DocumentListTests(unittest.TestCase):
    def test_a_complete_list(self):
        self.assertEqual(check_document_list(listing()), 3)

    def test_part_of_the_decided_sample_is_refused(self):
        for count in (0, 1, 2):  # 0, one, and N-1 documents of the N decided on
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    check_document_list(listing(count=count))

    def test_a_list_without_its_number_is_refused(self):
        documents = listing()
        del documents["expected_documents"]
        with self.assertRaises(ValueError):
            check_document_list(documents)

    def test_repeats_are_refused(self):
        for field, value in (("key", "01_00000001"), ("rank", 20), ("corp_code", "00000001"), ("pdf", "01.pdf"),
                             ("sha256", "text-1")):
            with self.subTest(field=field):
                documents = listing()
                documents["documents"][1][field] = value
                with self.assertRaises(ValueError):
                    check_document_list(documents)
        documents = listing()
        documents["documents"][2]["scans"]["tilt"]["sha256"] = "scan-1-normal"  # one scan file twice
        with self.assertRaises(ValueError):
            check_document_list(documents)

    def test_scans_and_paths(self):
        documents = listing()
        del documents["documents"][0]["scans"]["blur"]
        with self.assertRaises(ValueError):
            check_document_list(documents)
        for path in ("/tmp/x.gold.json", "../outside/x.gold.json"):
            with self.subTest(path=path):
                documents = listing()
                documents["documents"][0]["gold"] = path
                with self.assertRaises(ValueError):
                    check_document_list(documents)
                self.assertEqual(check_document_list(documents, repo_paths=False), 3)

    def test_the_registered_d4_list_is_its_ten_documents(self):
        path = ROOT / "eval" / "d4_eval" / "documents.json"
        self.assertTrue(is_d4_list(path, ROOT))
        self.assertEqual(check_document_list(json.loads(path.read_text(encoding="utf-8")), d4_legacy=True), 10)
        self.assertFalse(is_d4_list(ROOT / "eval" / "d5_eval" / "documents.json", ROOT))


class BundleTests(unittest.TestCase):
    def entries(self, names):
        return [{"name": name, "key": name.split(".")[0], "official_ready": True} for name in names]

    def test_a_bundle_of_all_its_calls(self):
        part = official_d4.bundle(self.entries(["a.text.ai", "b.text.ai"]), official_d4.CRITERIA["3.1"], 2)
        self.assertEqual(part["verdict"], "met")

    def test_a_bundle_with_fewer_or_repeated_calls_is_not_official(self):
        for names in (["a.text.ai"], ["a.text.ai", "a.text.ai"], []):
            with self.subTest(names=names):
                part = official_d4.bundle(self.entries(names), official_d4.CRITERIA["3.1"], 2)
                self.assertEqual(part["verdict"], "not official")
        self.assertEqual(official_d4.bundle(self.entries(["a.text.ai"]), official_d4.CRITERIA["3.1"])["verdict"], "not official")

    def test_the_aggregation_refuses_a_partial_list(self):
        with self.assertRaises(ValueError):
            official_d4.official(Path("unused"), Path("unused"), listing(count=2), {"documents": {}})


if __name__ == "__main__":
    unittest.main()
