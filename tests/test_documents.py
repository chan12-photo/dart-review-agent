"""Documents to verified spreadsheets (dart_review.documents).

The table, statement, and check logic run on synthetic words without any optional package. The PDF, OCR,
and Excel paths run on sample PDFs whose every value is known (samples.py) and are skipped when their
optional dependency is missing (pip install -e '.[docs]', brew install tesseract tesseract-lang).
"""

from importlib.util import find_spec
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.documents.samples import SampleStatement, korean_font, scan_pdf, text_pdf  # noqa: E402
from dart_review.documents.statement import account_of, clean_label, find_statements, parse_amount  # noqa: E402
from dart_review.documents.table import group_lines  # noqa: E402
from dart_review.documents.verify import REVIEW, check, separator_problem, uses_separators  # noqa: E402
from dart_review.documents.words import Word  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None and find_spec("pypdfium2") is not None
HAS_EXCEL = find_spec("openpyxl") is not None
HAS_OCR = HAS_PDF and shutil.which("tesseract") is not None and korean_font() is not None

BALANCE = SampleStatement(
    "재무상태표", "주식회사 예시", ["제 56 기 2025년 12월 31일 현재", "제 55 기 2024년 12월 31일 현재"], "백만원",
    ["제 56 (당) 기", "제 55 (전) 기"],
    [("자산", ["", ""]), ("Ⅰ. 유동자산", ["227,062,266", "202,945,624"]), ("Ⅱ. 비유동자산", ["296,597,320", "288,361,693"]),
     ("자산총계", ["523,659,586", "491,307,317"]), ("부채총계", ["112,339,878", "102,231,416"]),
     ("자본총계", ["411,319,708", "389,075,901"])])
INCOME = SampleStatement(
    "손익계산서", "주식회사 예시", ["제 56 기 2025년 1월 1일부터 2025년 12월 31일까지", "제 55 기 2024년 1월 1일부터 2024년 12월 31일까지"],
    "천원", ["제 56 (당) 기", "제 55 (전) 기"],
    [("매출액", ["333,605,938", "300,870,903"]), ("영업이익", ["43,601,051", "-"]), ("당기순이익(손실)", ["(1,234,567)", "34,451,351"])])

# a notes page after the statements: its tables must not be read as more rows of the last statement
NOTES = SampleStatement(
    "주석", "주식회사 예시", ["제 56 기 2025년 12월 31일 현재", "제 55 기 2024년 12월 31일 현재"], "백만원",
    ["당기말", "전기말"], [("보통예금", ["1,234,567", "1,111,111"]), ("정기예금", ["2,345,678", "2,222,222"])])
EQUITY = SampleStatement(
    "자본변동표", "주식회사 예시", ["제 56 기 2025년 1월 1일부터 2025년 12월 31일까지"], "백만원",
    ["자본금", "이익잉여금"], [("2025.1.1", ["897,514", "370,513,184"]), ("배당", ["-", "(9,809,438)"])])


def expected(statement: SampleStatement, unit: int) -> dict[str, list[int | None]]:
    return {clean_label(label): [parse_amount(text, unit) for text in amounts]
            for label, amounts in statement.rows if any(amounts)}


def words_for(rows: list[tuple[float, list[tuple[float, float, str]]]], page: int = 1) -> list[Word]:
    """Synthetic words: rows of (top, [(x0, x1, text)])."""
    return [Word(text, page, x0, x1, top, top + 9) for top, items in rows for x0, x1, text in items]


class AmountTests(unittest.TestCase):
    def test_amounts_as_printed(self):
        self.assertEqual(parse_amount("1,234", 1_000), 1_234_000)
        for printed in ("(1,234)", "△1,234", "-1,234", "（1,234）"):
            self.assertEqual(parse_amount(printed, 1), -1234, printed)
        self.assertIsNone(parse_amount("-", 1))
        with self.assertRaises(ValueError):
            parse_amount("주석", 1)

    def test_separators(self):
        self.assertIsNone(separator_problem("300,870,903"))
        self.assertIsNone(separator_problem("(1,234,567)"))
        self.assertIn("마침표", separator_problem("300,870.903"))  # the misread seen in the first OCR test
        self.assertIn("세 자리", separator_problem("3,00,870"))

    def test_labels(self):
        self.assertEqual(clean_label("Ⅰ. 유동자산"), "유동자산")
        self.assertEqual(clean_label("| . 유 동 자산", ocr=True), "유동자산")
        self.assertEqual(clean_label("현금및현금성자산 (주4,5)"), "현금및현금성자산")
        self.assertEqual(clean_label("© 비 유 동 자산", ocr=True), "비유동자산")
        self.assertEqual(clean_label("i. 비 유 동 자산", ocr=True), "비유동자산")  # OCR read "Ⅱ." as "i."
        self.assertEqual(account_of("당기순이익(손실)"), "net_income")
        self.assertEqual(account_of("자 산 총 계"), "total_assets")
        self.assertIsNone(account_of("자본총계"))


class TableTests(unittest.TestCase):
    ROWS = [(40, [(250, 300, "재무상태표")]),
            (60, [(250, 330, "제 56 기 2025년 12월 31일 현재")]),
            (80, [(470, 540, "(단위: 원)")]),
            (100, [(60, 90, "과 목"), (330, 380, "제 56 기"), (470, 520, "제 55 기")]),
            (120, [(60, 100, "자산총계"), (320, 380, "1,000"), (480, 520, "900")]),
            (140, [(60, 100, "부채총계"), (330, 380, "400"), (480, 520, "300")]),
            (160, [(60, 100, "자본총계"), (330, 380, "600"), (480, 520, "650")])]

    def test_a_statement_from_positions(self):
        [statement] = find_statements(group_lines(words_for(self.ROWS)))
        self.assertEqual((statement.kind, statement.unit), ("BS", 1))
        self.assertEqual([column.header for column in statement.columns], ["제 56 기", "제 55 기"])
        self.assertEqual(statement.columns[0].end, "2025-12-31")
        self.assertEqual([row.label for row in statement.rows], ["자산총계", "부채총계", "자본총계"])
        self.assertEqual(statement.rows[0].amounts[0].value, 1000)

    def test_the_balance_identity_marks_all_three_cells(self):
        [statement] = find_statements(group_lines(words_for(self.ROWS)))
        flagged = {(item.row, item.column) for item in check([statement]) if item.status == REVIEW}
        # 2025: 1,000 = 400 + 600 holds; 2024: 900 != 300 + 650, so its three cells need review
        self.assertEqual(flagged, {(0, 1), (1, 1), (2, 1)})

    def test_a_missing_unit_needs_review(self):
        rows = [row for row in self.ROWS if "단위" not in row[1][0][2]]
        [statement] = find_statements(group_lines(words_for(rows)))
        self.assertIsNone(statement.unit)
        self.assertTrue(all(item.status == REVIEW for item in check([statement])))

    def test_a_missing_separator_needs_review_where_the_document_uses_them(self):
        rows = [(40, [(250, 300, "손익계산서")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(60, 100, "매출액"), (320, 380, "333,605,938"), (460, 520, "300870903")]),
                (140, [(60, 100, "영업이익"), (320, 380, "43,601,051"), (460, 520, "32,725,961")]),
                (160, [(60, 100, "법인세비용"), (330, 380, "8,422,019"), (470, 520, "7,140,108")]),
                (180, [(60, 100, "당기순이익"), (320, 380, "34,451,351"), (460, 520, "23,567,302")])]
        [statement] = find_statements(group_lines(words_for(rows)))
        self.assertTrue(uses_separators([amount for row in statement.rows for amount in row.amounts.values()]))
        flagged = [(item.row, item.column, item.reasons) for item in check([statement]) if item.status == REVIEW]
        self.assertEqual([(row, column) for row, column, _ in flagged], [(0, 1)])



class RealLayoutTests(unittest.TestCase):
    """Layouts of the four real audit reports measured for v0.2, as synthetic words."""

    def test_the_unit_comes_from_the_statements_own_header_not_a_row_label(self):
        income = [(40, [(250, 300, "손익계산서")]), (80, [(470, 540, "(단위: 백만원)")]),
                  (100, [(60, 90, "과 목"), (330, 380, "제 57 기"), (470, 520, "제 56 기")]),
                  (120, [(60, 100, "매출액"), (320, 380, "333,605,938"), (460, 520, "300,870,903")]),
                  (140, [(60, 100, "당기순이익"), (320, 380, "45,206,805"), (460, 520, "34,451,351")]),
                  (160, [(60, 160, "기본주당이익(단위 : 원)"), (340, 380, "6,605"), (480, 520, "4,950")])]
        comprehensive = [(40, [(250, 300, "포괄손익계산서")]), (80, [(470, 540, "(단위: 백만원)")]),
                         (100, [(60, 90, "과 목"), (330, 380, "제 57 기"), (470, 520, "제 56 기")]),
                         (120, [(60, 100, "당기순이익"), (320, 380, "45,206,805"), (460, 520, "34,451,351")]),
                         (140, [(60, 100, "총포괄손익"), (320, 380, "51,290,524"), (460, 520, "51,296,338")])]
        lines = group_lines(words_for(income, page=1) + words_for(comprehensive, page=2))
        first, second = find_statements(lines)
        self.assertEqual((first.unit, second.unit), (1_000_000, 1_000_000))
        self.assertEqual(second.rows[1].amounts[0].value, 51_290_524_000_000)
        self.assertEqual((first.rows[2].label, first.rows[2].amounts[0].value), ("기본주당이익", 6_605))

    def test_left_aligned_period_headings_over_detail_and_subtotal_positions(self):
        rows = [(40, [(250, 300, "재무상태표")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(52, 58, "과"), (74, 80, "목"), (181, 197, "주 석"), (238, 275, "제26(당) 기말"),
                       (392, 430, "제25(전) 기말")]),
                (120, [(52, 76, "유동자산"), (336, 388, "2,928,529"), (490, 543, "2,286,147")]),
                (140, [(52, 100, "현금"), (197, 217, "4,5,6"), (264, 311, "1,000,000"), (418, 466, "900,000")]),
                (160, [(52, 100, "재고자산"), (204, 211, "10"), (264, 311, "1,928,529"), (418, 466, "1,386,147")]),
                (180, [(52, 82, "비유동자산"), (336, 388, "12,345"), (490, 543, "6,789")]),
                (200, [(52, 240, "기타포괄손익-공정가치 측정 지분상품 평가손익"), (264, 311, "12,345"), (418, 466, "6,789")])]
        [statement] = find_statements(group_lines(words_for(rows)))
        values = {row.label: [row.amounts[c].printed for c in sorted(row.amounts)] for row in statement.rows}
        self.assertEqual(values["유동자산"], ["2,928,529", "2,286,147"])  # the subtotal stays in its own period
        self.assertEqual(values["현금"], ["1,000,000", "900,000"])
        self.assertEqual(values["기타포괄손익-공정가치 측정 지분상품 평가손익"], ["12,345", "6,789"])
        self.assertFalse([problem for problem in statement.problems if "빈 칸" in problem or "넣지 못한" in problem])

    def test_a_label_wrapped_around_its_amounts(self):
        rows = [(40, [(250, 300, "현금흐름표")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(52, 196, "당기손익금융자산의 증가"), (320, 380, "(182,553)"), (460, 520, "(55,032)")]),
                (136, [(52, 204, "기타포괄손익금융자산의 감")]),
                (145, [(320, 380, "122,448"), (460, 520, "126,768")]),
                (154, [(52, 58, "소")]),
                (180, [(52, 196, "배당금의 지급"), (320, 380, "(9,897)"), (460, 520, "(9,809)")])]
        [statement] = find_statements(group_lines(words_for(rows)))
        self.assertEqual([row.label for row in statement.rows],
                         ["당기손익금융자산의 증가", "기타포괄손익금융자산의 감 소", "배당금의 지급"])
        self.assertEqual(statement.problems, [])


    def test_a_business_report_layout(self):
        """영업보고서: numbered 별도 titles, a 결손금처리계산서 after the 포괄손익계산서, and a page-number footer."""
        page_35 = [(40, [(34, 200, "3. 별도포괄손익계산서")]), (80, [(470, 540, "(단위: 백만 원)")]),
                   (100, [(174, 187, "과목"), (343, 361, "제6기"), (501, 519, "제5기")]),
                   (120, [(89, 136, "Ⅰ. 당기순손실"), (388, 425, "(572,713)"), (550, 587, "(937,643)")]),
                   (140, [(89, 144, "Ⅱ. 기타포괄손익"), (399, 425, "15,606"), (560, 587, "53,229")]),
                   (160, [(89, 151, "Ⅲ. 당기총포괄손실"), (388, 425, "(557,107)"), (550, 587, "(884,414)")]),
                   (750, [(85, 134, "Part 3. 재무제표"), (581, 590, "35")])]
        page_36 = [(77, [(34, 209, "4. 별도결손금처리계산서")]), (130, [(497, 538, "(단위: 백만 원)")]),
                   (146, [(289, 307, "제6기"), (450, 468, "제5기")]),
                   (172, [(38, 88, "I. 미처리결손금"), (334, 375, "(2,492,044)"), (495, 536, "(1,938,044)")]),
                   (188, [(48, 120, "전기이월미처리결손금"), (253, 294, "(1,938,044)"), (415, 455, "(1,051,712)")]),
                   (216, [(48, 84, "당기순손실"), (259, 294, "(572,713)"), (421, 455, "(937,643)")]),
                   (244, [(38, 119, "II. 차기이월미처리결손금"), (334, 375, "(2,492,044)"), (495, 536, "(1,938,044)")])]
        lines = group_lines(words_for(page_35, page=35) + words_for(page_36, page=36))
        comprehensive, deficit = find_statements(lines)
        self.assertEqual((comprehensive.kind, comprehensive.title, comprehensive.consolidated),
                         ("CIS", "별도포괄손익계산서", False))
        self.assertEqual([row.label for row in comprehensive.rows], ["당기순손실", "기타포괄손익", "당기총포괄손실"])
        self.assertEqual(comprehensive.problems, [])
        self.assertEqual((deficit.kind, deficit.title), ("RE", "별도결손금처리계산서"))
        values = {row.label: [row.amounts[c].printed for c in sorted(row.amounts)] for row in deficit.rows}
        self.assertEqual(values["전기이월미처리결손금"], ["(1,938,044)", "(1,051,712)"])


class OcrDamageTests(unittest.TestCase):
    """What a degraded scan did in the stress test, on synthetic OCR words."""

    def ocr_words(self, rows, confidence=95.0):
        return [Word(text, 1, x0, x1, top, top + 9, "ocr", confidence, (1, 1, number))
                for number, (top, items) in enumerate(rows) for x0, x1, text in items]

    def test_a_number_split_after_a_separator_is_joined(self):
        rows = [(40, [(250, 300, "재무상태표")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(60, 100, "비유동자산"), (320, 380, "296,597,320"), (455, 470, "288,"), (472, 520, "361,693")]),
                (140, [(60, 100, "자산총계"), (320, 380, "523,659,586"), (460, 520, "491,307,317")])]
        [statement] = find_statements(group_lines(self.ocr_words(rows)))
        self.assertEqual(statement.rows[0].amounts[1].printed, "288,361,693")
        self.assertEqual(statement.rows[0].amounts[1].value, 288_361_693)

    def test_an_unplaced_number_marks_its_row(self):
        rows = [(40, [(250, 300, "손익계산서")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(60, 100, "매출액"), (320, 380, "333,605,938"), (400, 430, "777,000"), (460, 520, "300,870,903")]),
                (140, [(60, 100, "영업이익"), (320, 380, "43,601,051"), (460, 520, "32,725,961")]),
                (160, [(60, 100, "당기순이익"), (320, 380, "34,451,351"), (460, 520, "23,567,302")])]
        [statement] = find_statements(group_lines(self.ocr_words(rows)))
        self.assertEqual(statement.rows[0].unplaced, 1)
        flagged = {(item.row, item.column) for item in check([statement]) if item.status == REVIEW}
        self.assertEqual(flagged, {(0, 0), (0, 1)})
        self.assertTrue(any("표에 넣지 못한 금액 1개" in problem for problem in statement.problems))

    def test_a_balance_sheet_without_its_totals_says_it_was_not_checked(self):
        rows = [(40, [(250, 300, "재무상태표")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(60, 100, "자산총계"), (330, 380, "1,000"), (480, 520, "900")]),
                (140, [(60, 100, "부채출계"), (330, 380, "400"), (480, 520, "300")])]  # "총" misread
        [statement] = find_statements(group_lines(self.ocr_words(rows)))
        self.assertIn("자산총계·부채총계·자본총계 줄을 모두 찾지 못해 합계 검산을 하지 못했다", statement.problems)

    def test_an_empty_cell_is_reported(self):
        rows = [(40, [(250, 300, "손익계산서")]), (80, [(470, 540, "(단위: 원)")]),
                (100, [(60, 90, "과 목"), (330, 380, "당기"), (470, 520, "전기")]),
                (120, [(60, 100, "매출액"), (320, 380, "333,605,938"), (460, 520, "300,870,903")]),
                (140, [(60, 100, "영업이익"), (320, 380, "43,601,051")]),
                (160, [(60, 100, "당기순이익"), (320, 380, "34,451,351"), (460, 520, "23,567,302")])]
        [statement] = find_statements(group_lines(self.ocr_words(rows)))
        self.assertTrue(any(problem.startswith("빈 칸 1개 (영업이익)") for problem in statement.problems), statement.problems)


class SubtotalTests(unittest.TestCase):
    """Detail amounts printed left of their subtotal in each period (nested columns), as in audit reports."""

    def rows(self, other_payables="7,953,586"):
        # 당기: details end at x 380, subtotals at x 440; 전기: details at 520, subtotals at 580
        return [(40, [(250, 300, "재무상태표")]), (80, [(470, 540, "(단위: 백만원)")]),
                (100, [(60, 90, "과 목"), (360, 420, "제 57 (당) 기"), (500, 560, "제 56 (전) 기")]),
                (120, [(60, 100, "비유동부채"), (390, 440, "24,210,425"), (530, 580, "19,013,579")]),
                (140, [(60, 100, "사채"), (340, 380, "7,134"), (480, 520, "14,530")]),
                (160, [(60, 100, "장기차입금"), (330, 380, "6,479,517"), (470, 520, "3,935,860")]),
                (180, [(60, 100, "장기미지급금"), (330, 380, "5,602,031"), (470, 520, "5,510,455")]),
                (200, [(60, 100, "순확정급여부채"), (330, 380, "558,520"), (470, 520, "521,410")]),
                (220, [(60, 100, "이연법인세부채"), (330, 380, "709,226"), (470, 520, "528,231")]),
                (240, [(60, 100, "장기충당부채"), (330, 380, "2,900,411"), (470, 520, "3,120,044")]),
                (260, [(60, 100, "기타비유동부채"), (330, 380, other_payables), (470, 520, "5,383,049")]),
                (280, [(60, 100, "부채총계"), (390, 440, "130,621,773"), (530, 580, "112,339,878")])]

    def test_subtotals_that_add_up_are_not_marked(self):
        [statement] = find_statements(group_lines(words_for(self.rows())))
        self.assertEqual([item for item in check([statement]) if item.status == REVIEW], [])

    def test_a_misread_detail_marks_its_subtotal_and_details(self):
        # the digit misread the same way by the model and by OCR on a real photo
        [statement] = find_statements(group_lines(words_for(self.rows("7,963,586"))))
        flagged = {(statement.rows[item.row].label, item.column) for item in check([statement]) if item.status == REVIEW}
        self.assertIn(("기타비유동부채", 0), flagged)
        self.assertIn(("비유동부채", 0), flagged)
        self.assertNotIn(("기타비유동부채", 1), flagged)  # the prior period adds up


@unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
class TextPdfTests(unittest.TestCase):
    def test_every_value_of_a_text_pdf(self):
        from dart_review.documents import extract
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [BALANCE, INCOME])
            result = extract(path, ocr="never")
        self.assertEqual(result.pages_by_method, {"text": [1, 2]})
        balance, income = result.statements
        self.assertEqual({row.label: [row.amounts[c].value for c in sorted(row.amounts)] for row in balance.rows},
                         expected(BALANCE, 1_000_000))
        self.assertEqual({row.label: [row.amounts[c].value for c in sorted(row.amounts)] for row in income.rows},
                         expected(INCOME, 1_000))
        self.assertEqual([(c.year, c.end) for c in balance.columns], [(2025, "2025-12-31"), (2024, "2024-12-31")])
        self.assertEqual([c.header for c in balance.columns], ["제 56 (당) 기", "제 55 (전) 기"])
        self.assertEqual(result.needs_review, 0)


    def test_only_the_asked_pages_are_read(self):
        from dart_review.documents import extract
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [BALANCE, INCOME])
            result = extract(path, ocr="never", pages=[2])
        self.assertEqual([statement.kind for statement in result.statements], ["IS"])
        self.assertEqual(result.pages_by_method, {"text": [2]})

    def test_the_notes_end_the_statements_and_a_matrix_statement_is_not_read(self):
        from dart_review.documents import extract
        from dart_review.documents.statement import SCE_SKIPPED
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [BALANCE, EQUITY, INCOME, NOTES])
            result = extract(path, ocr="never")
        balance, equity, income = result.statements
        self.assertEqual((equity.kind, equity.rows, equity.problems), ("SCE", [], [SCE_SKIPPED]))
        self.assertEqual([row.label for row in income.rows], [label for label, _ in INCOME.rows])
        self.assertEqual(income.problems, [])  # no note amount left over as an orphan
        self.assertEqual(result.needs_review, 0)


@unittest.skipUnless(HAS_OCR, "needs pdfplumber, pypdfium2, tesseract with kor, and a Korean font")
class ScanTests(unittest.TestCase):
    def test_a_scan_is_read_by_ocr_and_checked(self):
        from dart_review.documents import extract
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "scan.pdf"
            scan_pdf(path, [BALANCE, INCOME])
            result = extract(path, ocr="auto")
        self.assertEqual(result.pages_by_method, {"ocr": [1, 2]})
        balance, income = result.statements
        wrong, unread = [], []
        for statement, sample, unit in ((balance, BALANCE, 1_000_000), (income, INCOME, 1_000)):
            rows = {row.label: row for row in statement.rows}
            for label, values in expected(sample, unit).items():
                for column, value in enumerate(values):
                    amount = rows[label].amounts.get(column) if label in rows else None
                    if amount is None:
                        unread.append((statement, label))
                    elif amount.value != value:
                        wrong.append((label, amount.printed, value))
        # no wrong value on a clean scan; a cell OCR could not read (a lone "-" may vanish) must be reported
        self.assertEqual(wrong, [])
        for statement, label in unread:
            self.assertTrue(any(label in problem for problem in statement.problems), (label, statement.problems))

    def test_a_scan_too_poor_to_read_says_so(self):
        from dart_review.documents import extract
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "poor.pdf"
            scan_pdf(path, [BALANCE], dpi=90, rotate=2.5, blur=1.6)
            result = extract(path, ocr="auto")
        self.assertTrue(any("스캔 품질이 낮다" in problem for problem in result.problems), result.problems)


@unittest.skipUnless(HAS_PDF and HAS_EXCEL, "pip install -e '.[docs]'")
class WorkbookTests(unittest.TestCase):
    def test_sheets_values_and_marked_cells(self):
        from openpyxl import load_workbook
        from dart_review.documents import extract
        rows = list(BALANCE.rows)
        rows[-1] = ("자본총계", ["411,319,709", "389,075,901"])  # breaks the 2025 balance identity on purpose
        broken = SampleStatement(BALANCE.title, BALANCE.company, BALANCE.period_lines, BALANCE.unit, BALANCE.headers, rows)
        with tempfile.TemporaryDirectory() as folder:
            path, out = Path(folder) / "sample.pdf", Path(folder) / "sample.xlsx"
            text_pdf(path, [broken])
            result = extract(path, out, ocr="never")
            book = load_workbook(out)
        self.assertEqual(book.sheetnames, ["안내", "재무제표", "셀 출처", "검증"])
        self.assertEqual(result.needs_review, 3)
        sheet = book["재무제표"]
        marked = [cell for row in sheet.iter_rows() for cell in row if cell.comment is not None]
        self.assertEqual(len(marked), 3)
        self.assertTrue(all("자산총계 = 부채총계 + 자본총계" in cell.comment.text for cell in marked))
        values = {row[0].value: row[2].value for row in sheet.iter_rows(min_row=3) if row[0].value}
        self.assertEqual(values["자산총계"], 523_659_586_000_000)
        self.assertEqual(book["검증"].max_row, 4)  # header + three cells


if __name__ == "__main__":
    unittest.main()
