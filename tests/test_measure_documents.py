"""The development measurement's classification (eval/measure_documents.py), on Codex's counterexamples (D4 review).

Version 1 counted a same value under another account and any opposite sign as right, lost a missing row whose
value was elsewhere in the statement, and confirmed any number printed on the row's line. These build tiny
extractions by hand; no PDF, no OpenDART call.
"""

from pathlib import Path
import sys
from types import SimpleNamespace as N
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.documents.table import Cell, Line  # noqa: E402
from dart_review.documents.words import Word  # noqa: E402
from eval.measure_documents import classify  # noqa: E402


def cell(text, x0, x1, top=100):
    return Cell([Word(text, 1, x0, x1, top, top + 10, "text")])


def one(kind, label, value, printed, dart, lines=None, x=(300, 350)):
    """One extracted cell (period 0) against OpenDART items ``dart`` [(name, value)], with optional text lines."""
    amount = N(value=value, printed=printed, cell=cell(printed, *x))
    statement = N(kind=kind, title="연결" + {"BS": "재무상태표", "IS": "손익계산서", "CF": "현금흐름표"}[kind], page=1,
                  unit=1, unit_text="원", columns=[N(), N()], rows=[N(label=label, amounts={0: amount})],
                  problems=[], sums_checked=None)
    items = [{"sj_div": kind, "account_nm": name, "thstrm_amount": str(v)} for name, v in dart]
    result = classify(N(statements=[statement], checks=[], problems=[]), {"CFS": items}, lines or {})
    return result["statements"][0]


class MeasurementTests(unittest.TestCase):
    def test_a_value_of_another_account_is_not_a_confirmed_label(self):
        s = one("IS", "매출액", 1000, "1,000", [("영업이익", 1000)])
        self.assertEqual(s["review"][0]["label_class"], "label_review")  # a person compares the names

    def test_an_opposite_sign_outside_a_cash_flow_statement_is_reviewed(self):
        s = one("BS", "자산총계", -1000, "(1,000)", [("자산총계", 1000)])
        self.assertEqual(s["classes"]["sign_review"], 1)
        s = one("CF", "유형자산의 취득", -1000, "(1,000)", [("유형자산의취득", 1000)])
        self.assertEqual(s["classes"]["dart_sign_cf"], 1)

    def test_a_missing_row_whose_value_is_elsewhere_is_still_missing(self):
        s = one("BS", "유동자산", 1000, "1,000", [("유동자산", 1000), ("비유동자산", 1000)])
        self.assertEqual([(m["dart_name"], m["value"], m["status"]) for m in s["missing"]], [("비유동자산", 1000, "silent")])

    def test_a_number_on_the_line_but_in_the_other_periods_slot_is_not_confirmed(self):
        line = Line(1, [cell("매출액", 20, 60), cell("1,000", 300, 350), cell("2,000", 500, 550)])
        s = one("IS", "매출액", 2000, "2,000", [("매출액", 9999)], {1: [line]}, x=(500, 550))
        self.assertEqual(s["classes"]["unconfirmed"], 1)

    def test_a_number_in_its_own_slot_under_its_label_is_confirmed_when_the_unit_is(self):
        line = Line(1, [cell("기타일반관리비", 20, 60), cell("(1,211)", 300, 350), cell("(1,175)", 500, 550)])
        statement = N(kind="IS", title="연결손익계산서", page=1, unit=1, unit_text="원", columns=[N(), N()],
                      rows=[N(label="매출액", amounts={0: N(value=5000, printed="5,000", cell=cell("5,000", 300, 350, 80))}),
                            N(label="기타일반관리비", amounts={0: N(value=-1211, printed="(1,211)", cell=cell("(1,211)", 300, 350))})],
                      problems=[], sums_checked=None)
        items = [{"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "5000"},
                 {"sj_div": "IS", "account_nm": "기타일반관리비", "thstrm_amount": "1210"}]
        s = classify(N(statements=[statement], checks=[], problems=[]), {"CFS": items}, {1: [line]})["statements"][0]
        self.assertEqual((s["classes"]["dart_exact"], s["classes"]["pdf_confirmed"]), (1, 1))

    def test_a_per_share_amount_quoted_in_won_under_a_million_won_table_is_reported(self):
        amount = N(value=1_000_000, printed="1", cell=cell("1", 300, 350))
        statement = N(kind="IS", title="별도손익계산서", page=1, unit=1_000_000, unit_text="백만원", columns=[N(), N()],
                      rows=[N(label="매출", amounts={0: amount})], problems=["35쪽: 원본의 금액 '(2,447) 원'를 AI가 읽지 않았다"],
                      sums_checked=None)
        items = [{"sj_div": "IS", "account_nm": "매출", "thstrm_amount": "1000000"},
                 {"sj_div": "IS", "account_nm": "기본주당손실", "thstrm_amount": "-2447"}]
        result = classify(N(statements=[statement], checks=[], problems=[]), {"OFS": items, "CFS": []}, {})
        self.assertEqual(result["statements"][0]["missing"][0]["status"], "reported")

    def test_a_missing_value_named_in_a_problem_is_reported_and_a_band_failure_is_generic(self):
        s = one("IS", "매출액", 1000, "1,000", [("매출액", 1000), ("영업이익", 47)])
        self.assertEqual(s["missing"][0]["status"], "silent")
        amount = N(value=1000, printed="1,000", cell=cell("1,000", 300, 350))
        for problem, status in (("10쪽: 원본의 금액 '47'를 AI가 읽지 않았다", "reported"),
                                ("AI가 한 부분을 읽지 못했다: the model ran out of its output budget on one band", "generic")):
            statement = N(kind="IS", title="연결손익계산서", page=1, unit=1, unit_text="원", columns=[N(), N()],
                          rows=[N(label="매출액", amounts={0: amount})], problems=[problem], sums_checked=None)
            items = [{"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1000"},
                     {"sj_div": "IS", "account_nm": "영업이익", "thstrm_amount": "47"}]
            result = classify(N(statements=[statement], checks=[], problems=[]), {"CFS": items}, {})
            self.assertEqual(result["statements"][0]["missing"][0]["status"], status)


if __name__ == "__main__":
    unittest.main()
