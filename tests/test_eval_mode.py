"""The 3-1 evaluation mode and the model-only method (docs/EVAL_CONTRACT_3-1.ko.md sections 3, 4.4, 7).

No sealed data is read here: only company names (the public company list) and
the development cache.
"""

from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "eval"), str(ROOT / "tests")]

import run_eval  # noqa: E402
from dart_review.baseline import read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import (  # noqa: E402
    SEALED_EVAL_COMPANIES, SealedCompanyError, active_set, ensure_not_sealed, supported_companies, using_company_set,
)
from dart_review.company_names import resolve_company  # noqa: E402
from dart_review.crosscheck import crosscheck_turn  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402
from test_crosscheck import model_reading  # noqa: E402

REFERENCE = date(2026, 10, 8)


class CompanySetTests(unittest.TestCase):
    def test_development_is_the_default_and_refuses_the_sealed_companies(self):
        self.assertEqual(active_set().name, "development")
        self.assertEqual(resolve_company("NAVER 매출").kind, "sealed")
        with self.assertRaises(SealedCompanyError):
            ensure_not_sealed("00266961")

    def test_the_evaluation_set_is_the_contract_table(self):
        cases = {"네이버 매출": ("company", "NAVER"), "엔솔 매출": ("company", "LG에너지솔루션"),
                 "LG엔솔 영업이익": ("company", "LG에너지솔루션"), "씨제이제일제당 순이익": ("company", "CJ제일제당"),
                 "cj의 영업이익 부탁해": ("group", "CJ"), "LG 매출": ("group", "LG"), "CJ대한통운 매출": ("unsupported", "CJ대한통운"),
                 "케이엔솔 매출": ("unsupported", "케이엔솔"), "롯데하이마트 매출": ("unsupported", "롯데하이마트"),
                 "삼성전자 매출": ("unsupported", "삼성전자")}
        with using_company_set("sealed-3-1"):
            self.assertEqual(set(supported_companies()), set(SEALED_EVAL_COMPANIES))
            ensure_not_sealed("00266961")  # allowed only here
            for text, (kind, name) in cases.items():
                with self.subTest(text=text):
                    match = resolve_company(text)
                    self.assertEqual((match.kind, match.name if kind != "company" else supported_companies()[match.corp_code]),
                                     (kind, name))
            reading = read("cj의 영업이익 부탁해", REFERENCE)
            self.assertEqual((reading.kind, reading.options), ("clarify_company", ("CJ제일제당",)))
        self.assertEqual(active_set().name, "development")  # restored

    def test_the_contract_hash_follows_the_active_set(self):
        development = run_eval.company_set_hash()
        with using_company_set("sealed-3-1"):
            self.assertNotEqual(run_eval.company_set_hash(), development)


@unittest.skipUnless(run_eval.CACHE.exists(), "run scripts/fetch_dev_cache.py first")
class ModelOnlyTests(unittest.TestCase):
    def setUp(self):
        self.client = DartClient(ResponseCache(run_eval.CACHE), key_loader=lambda: (_ for _ in ()).throw(AssertionError()),
                                 offline=True)

    def tearDown(self):
        self.assertEqual(self.client.network_requests, 0)

    def turn(self, question, content):
        record = {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}
        crosscheck_turn(question, self.client, record, ScriptedChat([Reply(content)]).chat, REFERENCE, use_rules=False)
        return record

    def test_the_model_reading_decides_alone_and_both_keys_are_recorded(self):
        # p06: the rules read a year-over-year comparison, the model the previous quarter; model only answers
        record = self.turn("카카오 2023년 7~9월 매출이 4~6월보다 얼마나 늘었어?", json.dumps(model_reading("dev06"), ensure_ascii=False))
        self.assertEqual(record["readings"]["used"], "model only")
        self.assertIsNotNone(record["readings"]["rule_key"])
        self.assertNotEqual(record["readings"]["rule_key"], record["readings"]["model_key"])
        self.assertTrue(record["answer"]["answer"].startswith("이렇게 이해했습니다:"))
        self.assertEqual(record["answer"]["status"], "비교 가능")

    def test_no_model_reading_means_no_answer_even_if_the_rules_read_it(self):
        record = self.turn("삼성전자 2025년 매출액이 전년보다 얼마나 늘었어?", "not json")
        self.assertEqual(record["readings"]["used"], "none")
        self.assertIsNone(record["answer"])
        self.assertIsNotNone(record["readings"]["rule_key"])


if __name__ == "__main__":
    unittest.main()
