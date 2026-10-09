"""v0.1.2: the product defects the 3-5 evaluation found (eval/template_3-5/REPORT.md section 4).

Each test uses the development companies or synthetic rows; the 3-5 questions are not used here, so these
fixes are not tuned on them (the fixed version is to be measured on new questions).
"""

from datetime import date
import io
import json
from pathlib import Path
import re
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from dart_review.accounts import NOT_FOUND, resolve_account  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.company_names import korean_name  # noqa: E402
from dart_review.companies import DEV_COMPANIES, ENGLISH_NAMES, SEALED_EVAL_COMPANIES  # noqa: E402
from dart_review.compare import NEEDS_REVIEW, NO_DATA, NOT_FOUND_REASON, missing_result  # noqa: E402
from dart_review.crosscheck import canonical, crosscheck_turn, same_reading  # noqa: E402
from dart_review.facts import Fact  # noqa: E402
from dart_review.llm import Reply, ScriptedChat  # noqa: E402
from dart_review.periods import Period, Source  # noqa: E402
from dart_review.render import company_clarification_answer, polite  # noqa: E402
import judge  # noqa: E402

DEMO = ROOT / "demo" / "opendart"
CACHE = ROOT / "cache"


class EnglishNameTests(unittest.TestCase):
    """Defect 1: a model's reading named the company in English and was taken for another reading."""

    def test_an_official_english_name_maps_to_the_registered_korean_name(self):
        for written, korean in (("LG Energy Solution", "LG에너지솔루션"), ("LG ENERGY SOLUTION, LTD.", "LG에너지솔루션"),
                                ("Samsung Electronics Co., Ltd.", "삼성전자"), ("kakao corp", "카카오"),
                                ("NAVER", "NAVER"), ("삼성전자", "삼성전자")):
            with self.subTest(written=written):
                self.assertEqual(korean_name(written), korean)

    def test_an_abbreviation_is_not_guessed(self):
        # "LG ENSOL" (3-5 A2-047) is not an official name: it stays as written and is not mapped
        self.assertEqual(korean_name("LG ENSOL"), "LG ENSOL")
        self.assertEqual(korean_name("LG"), "LG")

    @unittest.skipUnless(CACHE.exists(), "run scripts/fetch_dev_cache.py first")
    def test_the_names_are_the_ones_in_corpcode_xml(self):
        body = next((CACHE / "corpCode.xml").glob("*.body")).read_bytes()
        archive = zipfile.ZipFile(io.BytesIO(body))
        xml = archive.read(archive.namelist()[0]).decode("utf-8")
        for corp_code, english in ENGLISH_NAMES.items():
            with self.subTest(corp_code=corp_code):
                found = re.search(rf"<corp_code>{corp_code}</corp_code>\s*<corp_name>([^<]*)</corp_name>\s*"
                                  rf"<corp_eng_name>([^<]*)</corp_eng_name>", xml)
                self.assertEqual(found.groups(), ({**DEV_COMPANIES, **SEALED_EVAL_COMPANIES}[corp_code], english))

    def test_a_reading_in_english_agrees_with_the_rules(self):
        client = DartClient(ResponseCache(DEMO), offline=True)
        reply = {"action": "compare", "company": "SAMSUNG ELECTRONICS CO., LTD.", "basis": "연결", "account": "revenue",
                 "current_period": {"kind": "year_to_date", "year": 2025, "month": 12},
                 "base_period": {"kind": "year_to_date", "year": 2024, "month": 12}, "clarify_accounts": []}
        chat = ScriptedChat([Reply(json.dumps(reply, ensure_ascii=False))])
        record = {"tool_calls": [], "tool_call_count": 0, "seen": [], "no_result": False, "answer": None}
        crosscheck_turn("삼성전자 2025년 매출액이 전년보다 얼마나 늘었어?", client, record,
                        lambda messages, **kwargs: chat.chat(messages, **kwargs))
        self.assertEqual(record["readings"]["used"], "both")
        self.assertEqual(record["readings"]["model"]["company_as_written"], "SAMSUNG ELECTRONICS CO., LTD.")
        self.assertEqual(record["answer"]["status"], "비교 가능")


class OutOfScopeTests(unittest.TestCase):
    """Defect 3: an unknown company and a refusal without a company were not usable readings."""

    def test_an_unknown_company_the_user_wrote_is_out_of_scope(self):
        arguments = {"basis": "연결", "account": "revenue", "period": {"kind": "year_to_date", "year": 2025, "month": 12}}
        self.assertEqual(canonical("lookup", arguments, "현대자동차", (), "현대자동차 2025년 매출 알려줘"),
                         ("unsupported", "company"))
        # a name that is not in the question is not trusted (the model may have made it up)
        self.assertIsNone(canonical("lookup", arguments, "현대자동차", (), "삼성전자 2025년 매출 알려줘"))
        self.assertIsNone(canonical("lookup", arguments, "어느 회사"))

    def test_both_readers_refusing_agree(self):
        self.assertEqual(canonical("unsupported", {}, ""), ("unsupported", None))
        self.assertTrue(same_reading(("unsupported", "company"), ("unsupported", None)))
        self.assertTrue(same_reading(("unsupported", "00126380"), ("unsupported", "company")))
        self.assertFalse(same_reading(("lookup", "00126380"), ("unsupported", None)))


def fact(resolved_by, amount=None, notes=()):
    return Fact("00126380", "CFS", "operating_cash_flow", Source(2025, "11011", "thstrm"), Period(date(2025, 12, 31), 12),
                amount, "KRW" if amount is not None else None, None, None, None, None, resolved_by, notes)


class MissingValueTests(unittest.TestCase):
    """Defect 2: "no data" was said for a report that exists but whose row was not found."""

    def test_only_a_missing_report_is_no_data(self):
        self.assertEqual(missing_result([fact("no_data", notes=("OpenDART 013",))])[0], NO_DATA)
        status, reasons = missing_result([fact(NOT_FOUND, notes=("영업활동현금흐름 계정을 찾지 못함",))])
        self.assertEqual(status, NEEDS_REVIEW)
        self.assertIn(NOT_FOUND_REASON, reasons)
        self.assertEqual(missing_result([fact("no_data"), fact(NOT_FOUND)])[0], NEEDS_REVIEW)

    def test_the_observed_name_without_a_standard_id_is_the_account(self):
        rows = [{"sj_div": "CF", "account_id": "-표준계정코드 미사용-", "account_nm": "영업활동으로부터의 순현금유입",
                 "account_detail": "-"}]
        resolution = resolve_account(rows, "operating_cash_flow")
        self.assertIsNotNone(resolution.row)
        self.assertIn("계정명 '영업활동으로부터의 순현금유입'으로 찾음", resolution.notes[0])

    def test_a_wrong_no_figure_review_is_held_back_not_a_wrong_figure(self):
        case = {"answer": {"status": "확인 필요", "values": [], "change": None}, "score": {"format_error": None}}
        self.assertEqual(judge.outcome(case, {"decision": "answer"}, passed=False), "보류·무응답")
        shown = {"answer": {"status": "확인 필요", "values": [{"amount": 1}], "change": None}, "score": {"format_error": None}}
        self.assertEqual(judge.outcome(shown, {"decision": "answer"}, passed=False), "잘못된 수치 답")


class WordingTests(unittest.TestCase):
    """Defect 4: a terse clause inside a reason, and the particle after a group name."""

    def test_a_terse_clause_before_a_parenthesis(self):
        text = "2024-12-31 시점 값이 보고서마다 다르다(재작성): 접수번호 1에서 5 (이번 비교 기간에 미친 영향은 확인하지 못했다)"
        self.assertEqual(polite(text), "2024-12-31 시점 값이 보고서마다 다릅니다(재작성): 접수번호 1에서 5 "
                                       "(이번 비교 기간에 미친 영향은 확인하지 못했습니다)")

    def test_an_already_polite_ending_is_left_alone(self):
        self.assertEqual(polite("확인하지 못했습니다"), "확인하지 못했습니다")

    def test_the_topic_particle_after_a_group_name(self):
        for group, expected in (("LG", "'LG'는"), ("CJ", "'CJ'는"), ("엘지", "'엘지'는"), ("삼성", "'삼성'은")):
            with self.subTest(group=group):
                self.assertIn(expected, company_clarification_answer(group, ["후보"])["answer"])


if __name__ == "__main__":
    unittest.main()
