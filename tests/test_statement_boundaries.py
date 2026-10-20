"""Where one statement ends and the next begins, and a row's label on the page: the defects D4 found.

In the D4 evaluation (eval/d4_eval/results/2026-10-20/REPORT.ko.md) every unmarked wrong value was rows of one
statement put into another one's sheet, and one label the AI rewrote went through unmarked:
- DSR: "연결 자본변동표" with dotted period lines ("2025.01.01 부터 2025.12.31 까지") and a unit line split over two
  lines was not taken as a statement start; its rows went into the 포괄손익계산서 before it.
- 이노메트리 (scan): OCR read the title "연결포괄손의계산서"; its rows went into the 재무상태표 before it.
- 쌍용씨앤이: a label printed above and below its amounts; the AI reader kept the model's "당기순손익…".
- Rules reader on scans: a column heading that OCR ran together from several columns passed as a period.
"""

from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.documents import samples  # noqa: E402
from dart_review.documents.samples import SampleStatement, text_pdf  # noqa: E402
from dart_review.documents.statement import (  # noqa: E402
    UNTITLED, find_statements, is_statement_start, title_of, untitled_start,
)
from dart_review.documents.table import group_lines  # noqa: E402
from dart_review.documents.verify import REVIEW, check, one_period  # noqa: E402
from dart_review.documents.words import Word  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None and find_spec("pypdfium2") is not None


def page(page_number, *rows):
    """Lines of one page from (top, [(x, text), ...]) rows; a word is 6 points wide per character. Words at
    x >= 400 are right-aligned at x + 84 (the period columns, headings and amounts alike), others start at x."""
    words = []
    for top, cells in rows:
        for x, text in cells:
            x0 = x + 84 - 6 * len(text) if x >= 400 else x
            words.append(Word(text, page_number, x0, x0 + 6 * len(text), top, top + 8))
    return group_lines(words)


BALANCE = page(1, (50, [(250, "연결재무상태표")]), (64, [(200, "제 62 기 2025.12.31 현재")]),
               (78, [(400, "(단위 : 원)")]), (100, [(60, "과 목"), (400, "제 62 (당) 기"), (500, "제 61 (전) 기")]),
               (120, [(60, "유동자산"), (400, "183,887,864,169"), (500, "157,101,448,500")]),
               (136, [(60, "자산총계"), (400, "391,592,277,418"), (500, "363,394,228,331")]))


class StartTests(unittest.TestCase):
    def test_dotted_period_lines_and_a_spaced_title_start_a_statement(self):
        lines = page(11, (54, [(250, "연결 자본변동표")]), (69, [(200, "제 62 기 2025.01.01 부터 2025.12.31 까지")]),
                     (83, [(200, "제 61 기 2024.01.01 부터 2024.12.31 까지")]))
        self.assertTrue(is_statement_start(lines, 0))

    def test_a_unit_line_split_over_two_lines(self):
        lines = page(11, (54, [(250, "연결 자본변동표")]), (97, [(60, "DSR주식회사와 그 종속기업"), (400, "(단위 :")]),
                     (113, [(400, "원)")]))
        self.assertTrue(is_statement_start(lines, 0))

    def test_the_dsr_pages_are_four_statements_and_the_changes_in_equity(self):
        income = page(10, (54, [(250, "연결 포괄손익계산서")]), (69, [(200, "제 62 기 2025.01.01 부터 2025.12.31 까지")]),
                      (97, [(400, "(단위 : 원)")]), (120, [(60, "과 목"), (400, "제 62 (당) 기"), (500, "제 61 (전) 기")]),
                      (140, [(60, "당기순이익"), (400, "14,868,234,173"), (500, "14,512,806,208")]),
                      (156, [(60, "총포괄이익"), (400, "14,297,849,413"), (500, "17,309,316,826")]))
        equity = page(11, (54, [(250, "연결 자본변동표")]), (69, [(200, "제 62 기 2025.01.01 부터 2025.12.31 까지")]),
                      (97, [(60, "DSR주식회사와 그 종속기업"), (400, "(단위 :")]), (113, [(400, "원)")]),
                      (199, [(60, "당기순이익(손실)"), (300, "14,544,326,241"), (500, "14,512,806,208")]))
        statements = find_statements(income + equity)
        self.assertEqual([(s.kind, s.page) for s in statements], [("CIS", 10), ("SCE", 11)])
        self.assertEqual([row.label for row in statements[0].rows], ["당기순이익", "총포괄이익"])  # nothing of page 11

    def test_a_title_misread_by_ocr_starts_its_statement_and_marks_every_cell(self):
        self.assertEqual(title_of("연 결 포 괄 손 의 계 산서"), ("연결포괄손익계산서", False))
        income = page(2, (50, [(250, "연 결 포 괄 손 의 계 산서")]),
                      (64, [(200, "제 18( 당 ) 기 : 2025 년 1 월 1 일 부터 2025 년 12 월 31 일 까지")]),
                      (78, [(400, "(단위: 원)")]), (100, [(60, "과 목"), (400, "제 18 (당) 기"), (500, "제 17 (전) 기")]),
                      (120, [(60, "매출원가"), (400, "35,252,456,908"), (500, "42,004,230,524")]),
                      (136, [(60, "매출총이익"), (400, "3,315,234,793"), (500, "10,991,818,032")]))
        statements = find_statements(BALANCE + income)
        self.assertEqual([(s.kind, s.title) for s in statements], [("BS", "연결재무상태표"), ("CIS", "연결포괄손익계산서")])
        self.assertNotIn("매출원가", [row.label for row in statements[0].rows])
        marked = {(c.statement, c.row) for c in check(statements) if c.status == REVIEW
                  and any("제목을 원본에서 정확히 읽지 못했다" in r for r in c.reasons)}
        self.assertEqual(marked, {(1, 0), (1, 1)})
        self.assertFalse([c for c in check(statements) if c.statement == 0 and c.status == REVIEW])

    def test_titles_are_not_guessed_loosely(self):
        self.assertEqual(title_of("연결손익계산서"), ("연결손익계산서", True))
        self.assertEqual(title_of("포괄손익계산서"), ("포괄손익계산서", True))
        self.assertEqual(title_of("연결현금흐름"), ("연결현금흐름표", False))  # a letter lost: still that title, marked
        for text in ("연결재무제표", "주석", "재무제표에 대한 주석", "과 목", "감사보고서", "현금및현금성자산"):
            with self.subTest(text=text):
                self.assertIsNone(title_of(text))
        lines = page(2, (50, [(250, "연결포괄손의계산서")]), (78, [(400, "(단위: 원)")]))
        self.assertFalse(is_statement_start(lines, 0))  # an inexact title needs a dated period line
        dated = page(2, (50, [(250, "연결포괄손의계산서")]), (64, [(200, "제 18 기 2025년 1월 1일 부터 2025년 12월 31일 까지")]))
        self.assertTrue(is_statement_start(dated, 0))
        self.assertFalse(is_statement_start(dated, 0, in_notes=True))  # in the notes only an exact title

    def test_a_page_starting_like_a_statement_without_a_title_is_kept_apart(self):
        untitled = page(2, (64, [(200, "제 18 기 2025년 1월 1일 부터 2025년 12월 31일 까지")]), (78, [(400, "(단위: 원)")]),
                        (100, [(60, "과 목"), (400, "제 18 (당) 기"), (500, "제 17 (전) 기")]),
                        (120, [(60, "매출원가"), (400, "35,252,456,908"), (500, "42,004,230,524")]))
        statements = find_statements(BALANCE + untitled)
        self.assertEqual([s.kind for s in statements], ["BS", UNTITLED])
        self.assertEqual([row.label for row in statements[0].rows], ["유동자산", "자산총계"])
        self.assertTrue(all(c.status == REVIEW for c in check(statements) if c.statement == 1))

    def test_a_continuation_page_and_the_notes_are_not_new_statements(self):
        continued = page(2, (40, [(60, "비유동자산"), (400, "207,704,413,249"), (500, "206,292,779,831")]),
                         (56, [(60, "자산총계"), (400, "391,592,277,418"), (500, "363,394,228,331")]))
        self.assertFalse(untitled_start(continued))
        notes = page(2, (40, [(250, "주석")]), (54, [(200, "제 62 기 2025년 12월 31일 현재")]))
        self.assertFalse(untitled_start(notes))
        self.assertEqual(len(find_statements(BALANCE + continued)), 1)


class PeriodHeadingTests(unittest.TestCase):
    def test_one_period_per_heading(self):
        for header in ("제 57 (당) 기", "제 56 (전) 기", "제 56 기", "당기", "전기말", "2025.12.31", "2025년", "제 55 (전전) 기"):
            with self.subTest(header=header):
                self.assertTrue(one_period(header))
        for header in ("과목 00000 주석 0 ] 제 54( 당 기 ] 체 53( 전 기 ㅠㅠ", "| 5990 | 99099 46290. | samen]", "금 액", "",
                       "제 62 기 제 61 기", "2025년 2024년"):
            with self.subTest(header=header):
                self.assertFalse(one_period(header))


@unittest.skipUnless(HAS_PDF, "needs pdfplumber and pypdfium2")
class AiReaderTests(unittest.TestCase):
    """The AI reader on text PDFs, with a scripted model (no Ollama)."""

    class Model:
        name = "scripted"

        def __init__(self, answers):
            self.answers = list(answers)

        def transcribe(self, png, prompt):
            lines = self.answers.pop(0) if self.answers else []
            return "\n".join(f"{label} | {' | '.join(amounts)}" for label, amounts in lines)

    def read(self, statements, answers, layout=None):
        from dart_review.documents.ai_reader import read_document
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            if layout:
                with mock.patch.object(samples, "_layout", layout):
                    text_pdf(path, statements)
            else:
                text_pdf(path, statements)
            return read_document(path, self.Model(answers))

    def statement(self, title, period, rows):
        return SampleStatement(title, "주식회사 예시", [f"제 18 기 {period}"], "원", ["제 18 (당) 기", "제 17 (전) 기"], rows)

    def test_a_page_without_a_title_after_a_statement_is_kept_apart_and_marked(self):
        balance = [("유동자산", ["183,887,864,169", "157,101,448,500"]), ("자산총계", ["391,592,277,418", "363,394,228,331"])]
        income = [("매출원가", ["35,252,456,908", "42,004,230,524"]), ("매출총이익", ["3,315,234,793", "10,991,818,032"])]
        reading = self.read([self.statement("연결재무상태표", "2025년 12월 31일 현재", balance),
                             self.statement("", "2025년 1월 1일 부터 2025년 12월 31일 까지", income)], [balance, income])
        first, second = reading.statements
        self.assertEqual([row.label for row in first.rows], ["유동자산", "자산총계"])
        self.assertEqual((second.kind, [row.label for row in second.rows]), (UNTITLED, ["매출원가", "매출총이익"]))
        own = [c for c in reading.checks if c.statement == 1]
        self.assertTrue(own and all(c.status == REVIEW for c in own))
        self.assertFalse([c for c in reading.checks if c.statement == 0 and c.status == REVIEW])

    def test_a_misread_title_on_the_page_starts_its_statement_and_marks_every_cell(self):
        balance = [("유동자산", ["183,887,864,169", "157,101,448,500"]), ("자산총계", ["391,592,277,418", "363,394,228,331"])]
        income = [("매출원가", ["35,252,456,908", "42,004,230,524"])]
        reading = self.read([self.statement("연결재무상태표", "2025년 12월 31일 현재", balance),
                             self.statement("연결포괄손의계산서", "2025년 1월 1일 부터 2025년 12월 31일 까지", income)],
                            [balance, income])
        self.assertEqual([(s.kind, s.title) for s in reading.statements],
                         [("BS", "연결재무상태표"), ("CIS", "연결포괄손익계산서")])
        self.assertTrue(all(c.status == REVIEW for c in reading.checks if c.statement == 1))

    def test_a_label_printed_around_its_amounts_takes_the_page_label(self):
        def layout(statement, size=9.0):
            items = samples.PAGE_WIDTH / 2, 60
            items = [(samples.PAGE_WIDTH / 2, 60, statement.title, "center"),
                     (samples.PAGE_WIDTH / 2, 78, statement.period_lines[0], "center"),
                     (samples.PAGE_WIDTH - 50, 102, "(단위: 원)", "right"),
                     (60, 130, "과 목", "left"), (395, 130, "제 18 (당) 기", "right"), (545, 130, "제 17 (전) 기", "right"),
                     (60, 152, "기타포괄손익", "left"), (395, 152, "(1,744,266,493)", "right"), (545, 152, "112,930,561", "right"),
                     # printed as on 쌍용씨앤이 page 11: label, amounts, and the rest of the label 8 points apart
                     (60, 172, "당기손익으로 재분류되지 않는항목", "left"),
                     (395, 180, "(1,743,875,245)", "right"), (545, 180, "728,298,184", "right"),
                     (60, 188, "(세후기타포괄손익)", "left")]
            return items

        page_ = self.statement("포괄손익계산서", "2025년 1월 1일 부터 2025년 12월 31일 까지", [])
        model_rows = [("기타포괄손익", ["(1,744,266,493)", "112,930,561"]),
                      ("당기순손익으로 재분류되지 않는항목(세후기타포괄손익)", ["(1,743,875,245)", "728,298,184"])]
        reading = self.read([page_], [model_rows], layout=layout)
        statement = reading.statements[0]
        self.assertEqual([row.label.replace(" ", "") for row in statement.rows],
                         ["기타포괄손익", "당기손익으로재분류되지않는항목(세후기타포괄손익)"])
        self.assertIn("1쪽: AI가", " ".join(statement.problems))  # the model's label differed: reported

    def test_an_amount_line_with_no_label_on_the_page_is_marked(self):
        def layout(statement, size=9.0):
            return [(samples.PAGE_WIDTH / 2, 60, statement.title, "center"),
                    (samples.PAGE_WIDTH / 2, 78, statement.period_lines[0], "center"),
                    (samples.PAGE_WIDTH - 50, 102, "(단위: 원)", "right"),
                    (60, 130, "과 목", "left"), (395, 130, "제 18 (당) 기", "right"), (545, 130, "제 17 (전) 기", "right"),
                    (395, 152, "(1,743,875,245)", "right"), (545, 152, "728,298,184", "right")]

        page_ = self.statement("포괄손익계산서", "2025년 1월 1일 부터 2025년 12월 31일 까지", [])
        reading = self.read([page_], [[("당기순손익", ["(1,743,875,245)", "728,298,184"])]], layout=layout)
        marked = [c for c in reading.checks if c.status == REVIEW]
        self.assertEqual(len(marked), 2)
        self.assertIn("계정명을 찾지 못해", " ".join(marked[0].reasons))


if __name__ == "__main__":
    unittest.main()
