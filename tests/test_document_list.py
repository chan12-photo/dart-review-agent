"""The registered document list is complete and without repeats (eval/d4_eval/document_list.py, Codex D5 review 1),
its number of documents decided outside it, and its files inside the repository without a link (Codex D5 re-check
1-2)."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

from document_list import (check_document_list, is_d4_list, profile_record, registered_count)  # noqa: E402
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
        self.assertEqual(check_document_list(listing(), 3), 3)

    def test_part_of_the_decided_sample_is_refused(self):
        for count in (0, 1, 2):  # 0, one, and N-1 documents of the N decided on
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    check_document_list(listing(count=count), 3)

    def test_the_number_comes_from_outside_the_list(self):
        # Codex D5 re-check 1: a list of 1 (or 9) of the 10 decided on, saying so itself, passed
        for count in (1, 9):
            with self.subTest(count=count):
                part = listing(count=count, expected=count)
                with self.assertRaisesRegex(ValueError, "the profile 10"):
                    check_document_list(part, 10)
                with self.assertRaisesRegex(ValueError, "not given from outside the list"):
                    check_document_list(part)
        self.assertEqual(check_document_list(listing(count=10, expected=10), 10), 10)
        for expected in (None, 0, True, "3"):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                check_document_list(listing(), expected)

    def test_a_list_without_its_number_is_refused(self):
        documents = listing()
        del documents["expected_documents"]
        with self.assertRaises(ValueError):
            check_document_list(documents, 3)

    def test_repeats_are_refused(self):
        for field, value in (("key", "01_00000001"), ("rank", 20), ("corp_code", "00000001"), ("pdf", "01.pdf"),
                             ("sha256", "text-1")):
            with self.subTest(field=field):
                documents = listing()
                documents["documents"][1][field] = value
                with self.assertRaises(ValueError):
                    check_document_list(documents, 3)
        documents = listing()
        documents["documents"][2]["scans"]["tilt"]["sha256"] = "scan-1-normal"  # one scan file twice
        with self.assertRaises(ValueError):
            check_document_list(documents, 3)

    def test_scans_and_paths(self):
        documents = listing()
        del documents["documents"][0]["scans"]["blur"]
        with self.assertRaises(ValueError):
            check_document_list(documents, 3)
        for path in ("/tmp/x.gold.json", "../outside/x.gold.json", "eval/../../outside.json"):
            with self.subTest(path=path):
                documents = listing()
                documents["documents"][0]["gold"] = path
                with self.assertRaisesRegex(ValueError, "not a file inside the repository"):
                    check_document_list(documents, 3, root=ROOT)
                self.assertEqual(check_document_list(documents, 3), 3)  # no root: a fixture's own paths

    def test_the_registered_d4_list_is_its_ten_documents(self):
        path = ROOT / "eval" / "d4_eval" / "documents.json"
        self.assertTrue(is_d4_list(path, ROOT))
        self.assertEqual(registered_count(path, ROOT), ("d4", 10))
        self.assertEqual(check_document_list(json.loads(path.read_text(encoding="utf-8")), d4_legacy=True, root=ROOT), 10)
        self.assertFalse(is_d4_list(ROOT / "eval" / "d5_eval" / "documents.json", ROOT))


class LinkAndProfileTests(unittest.TestCase):
    """A repository of its own: D4's list, D5's list with its freeze record, and links (Codex D5 re-check 2)."""

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        self.outside = Path(temp.name) / "outside"
        self.outside.mkdir()
        (self.root / "eval" / "d4_eval").mkdir(parents=True)
        (self.root / "eval" / "d5_eval").mkdir(parents=True)
        self.d4 = self.root / "eval" / "d4_eval" / "documents.json"
        self.d4.write_text(json.dumps(listing(10, None)), encoding="utf-8")
        self.d5 = self.root / "eval" / "d5_eval" / "documents.json"
        self.d5.write_text(json.dumps(listing(3, 3)), encoding="utf-8")
        self.freeze = self.root / "eval" / "freeze_d5.json"
        self.freeze.write_text(json.dumps({"profile": profile_record("d5", 3)}), encoding="utf-8")

    def test_each_list_gets_its_evaluation_s_number(self):
        self.assertEqual(registered_count(self.d4, self.root), ("d4", 10))
        self.assertEqual(registered_count(self.d5, self.root), ("d5", 3))
        other = self.root / "eval" / "d5_eval" / "other.json"
        other.write_text(self.d5.read_text(encoding="utf-8"), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not the document list of a registered evaluation"):
            registered_count(other, self.root)

    def test_a_link_to_d4_s_list_is_not_d4_s_list(self):
        # Codex D5 re-check 2: a D5 list linked to D4's took D4's exception (N = 10 without a freeze record)
        link = self.root / "eval" / "d5_eval" / "linked.json"
        os.symlink(self.d4, link)
        self.assertFalse(is_d4_list(link, self.root))
        with self.assertRaises(ValueError):
            registered_count(link, self.root)
        self.d5.unlink()
        os.symlink(self.d4, self.d5)  # D5's own place, a link to D4's list
        with self.assertRaisesRegex(ValueError, "reached through a link"):
            registered_count(self.d5, self.root)

    def test_d4_s_place_reached_through_a_linked_folder(self):
        moved = self.outside / "d4_eval"
        (self.root / "eval" / "d4_eval").rename(moved)
        os.symlink(moved, self.root / "eval" / "d4_eval")
        self.assertFalse(is_d4_list(self.d4, self.root))

    def test_a_freeze_record_that_is_not_the_profile_s(self):
        for profile in ({}, {"profile": {**profile_record("d5", 3), "tag": "d4-registered"}},
                        {"profile": {**profile_record("d5", 3), "tool_paths": []}},
                        {"profile": {**profile_record("d5", 3), "expected_documents": 0}}):
            with self.subTest(profile=profile):
                self.freeze.write_text(json.dumps(profile), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "profile"):
                    registered_count(self.d5, self.root)
        self.freeze.unlink()
        target = self.outside / "freeze.json"
        target.write_text(json.dumps({"profile": profile_record("d5", 3)}), encoding="utf-8")
        os.symlink(target, self.freeze)
        with self.assertRaisesRegex(ValueError, "reached through a link"):
            registered_count(self.d5, self.root)

    def test_a_gold_linked_out_of_the_repository(self):
        # Codex D5 re-check 2: a link inside the repository to a file outside it passed a check of the spelling
        gold = self.root / "eval" / "d5_eval" / "gold"
        gold.mkdir()
        (self.outside / "01.gold.json").write_text("{}", encoding="utf-8")
        os.symlink(self.outside / "01.gold.json", gold / "01.gold.json")
        documents = listing()
        with self.assertRaisesRegex(ValueError, "01.gold.json is not a file inside the repository"):
            check_document_list(documents, 3, root=self.root)
        (gold / "01.gold.json").unlink()
        os.symlink(self.outside, gold / "linked")
        documents["documents"][0]["gold"] = "eval/d5_eval/gold/linked/01.gold.json"
        with self.assertRaisesRegex(ValueError, "not a file inside the repository"):
            check_document_list(documents, 3, root=self.root)


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
        for documents, expected in ((listing(count=2), 3), (listing(count=1, expected=1), 3), (listing(), None)):
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                official_d4.official(Path("unused"), Path("unused"), documents, {"documents": {}}, expected=expected)


if __name__ == "__main__":
    unittest.main()
