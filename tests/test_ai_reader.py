"""The AI-first reader (dart_review.documents.ai_reader): the model reads, the evidence confirms.

A scripted model stands in for the vision model, so these tests need no Ollama. They check the cases seen on
real documents: a misread digit, a label shifted by one row, a row the model skipped, an answer cut off,
and an unverified unit. Every wrong value must end up marked, never silently in the workbook.
"""

from importlib.util import find_spec
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.documents.samples import SampleStatement, text_pdf  # noqa: E402
from dart_review.documents.verify import REVIEW  # noqa: E402
from dart_review.documents.vision import META_PROMPT, VisionError, parse_band, parse_meta  # noqa: E402

HAS_PDF = find_spec("pdfplumber") is not None and find_spec("pypdfium2") is not None

SAMPLE = SampleStatement(
    "재무상태표", "주식회사 예시", ["제 57 기 2025년 12월 31일 현재", "제 56 기 2024년 12월 31일 현재"], "백만원",
    ["제 57 (당) 기", "제 56 (전) 기"],
    [("유동자산", ["247,684,612", "227,062,266"]), ("비유동자산", ["319,257,498", "287,469,682"]),
     ("자산총계", ["566,942,110", "514,531,948"]), ("유동부채", ["106,411,348", "93,326,299"]),
     ("비유동부채", ["24,210,425", "19,013,579"]), ("부채총계", ["130,621,773", "112,339,878"]),
     ("자본총계", ["436,320,337", "402,192,070"])])


class ScriptedModel:
    """Answers each band with the given lines; the band's rows are recognised by the labels it contains."""

    name = "scripted"

    def __init__(self, rows, fail=False):
        self.rows, self.fail, self.prompts = rows, fail, []

    def transcribe(self, png, prompt):
        self.prompts.append(prompt)
        if self.fail:
            raise VisionError("the model ran out of its output budget on one band")
        if prompt == META_PROMPT:
            return "제목: 재무상태표\n단위: 백만원\n열: 과목 | 제 57 (당) 기 | 제 56 (전) 기"
        return "\n".join(f"{label} | {' | '.join(amounts)}" for label, amounts in self.rows)


class ParseTests(unittest.TestCase):
    def test_band_lines(self):
        lines = parse_band("1. 현금및현금성자산 | 4, 29 | 57,856,378 | 53,705,579\n자산 |\n잡음\n선급비용 | 3,627,172 | ?")
        self.assertEqual([(line.label, line.amounts) for line in lines],
                         [("1. 현금및현금성자산", ["57,856,378", "53,705,579"]), ("선급비용", ["3,627,172"])])

    def test_meta(self):
        meta = parse_meta("제목: 연결재무상태표\n기간: 제57기: 2025년12월31일 현재\n단위: 백만원\n열: 과목 | 주석 | 제57(당)기 | 제56(전)기")
        self.assertEqual((meta.title, meta.unit, meta.columns[-2:]), ("연결재무상태표", "백만원", ["제57(당)기", "제56(전)기"]))


@unittest.skipUnless(HAS_PDF, "pip install -e '.[docs]'")
class TextLayerEvidenceTests(unittest.TestCase):
    def read(self, rows, fail=False):
        from dart_review.documents.ai_reader import read_document
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [SAMPLE])
            return read_document(path, ScriptedModel(rows, fail))

    def flagged(self, reading):
        statement = reading.statements[0]
        return {(statement.rows[c.row].label, c.column): c.reasons for c in reading.checks if c.status == REVIEW}

    def test_a_faithful_reading_is_confirmed_by_the_text_layer(self):
        reading = self.read(SAMPLE.rows)
        statement = reading.statements[0]
        self.assertEqual(self.flagged(reading), {})
        self.assertEqual({c.evidence for c in reading.checks}, {"PDF 글자"})
        self.assertEqual(statement.rows[2].amounts[0].value, 566_942_110_000_000)
        self.assertEqual([column.end for column in statement.columns], ["2025-12-31", "2024-12-31"])

    def test_a_misread_digit_is_marked(self):
        rows = list(SAMPLE.rows)
        rows[3] = ("유동부채", ["106,411,348", "98,326,299"])  # 93 read as 98
        flagged = self.flagged(self.read(rows))
        self.assertIn(("유동부채", 1), flagged)
        self.assertIn("원본에서 같은 숫자를 찾지 못했다", " ".join(flagged[("유동부채", 1)]))

    def test_a_label_shifted_by_one_row_takes_the_page_label_and_is_reported(self):
        rows = list(SAMPLE.rows)
        rows[0] = ("비유동자산", SAMPLE.rows[0][1])  # the model put the next label on the first row's numbers
        rows[1] = ("유동자산", SAMPLE.rows[1][1])
        reading = self.read(rows)
        statement = reading.statements[0]
        self.assertEqual([row.label for row in statement.rows[:2]], ["유동자산", "비유동자산"])  # the page's labels
        self.assertEqual(statement.rows[0].amounts[0].printed, "247,684,612")
        self.assertIn("1쪽: AI가 '유동자산' 줄을 '비유동자산'(으)로 읽어 원본 계정명을 썼다", statement.problems)
        self.assertEqual(self.flagged(reading), {})  # the output is the page's own label, digits, and column

    def test_left_aligned_headings_over_detail_and_subtotal_positions(self):
        from dart_review.documents.ai_reader import Header
        header = Header([238, 392], [], 0)  # 한화시스템: "제26(당) 기말" at 238, "제25(전) 기말" at 392
        self.assertEqual([header.period_of(right) for right in (217, 311, 388, 466, 543)], [None, 0, 0, 1, 1])

    def test_labels_inside_one_another_are_different_accounts(self):
        from dart_review.documents.ai_reader import _different_accounts
        self.assertTrue(_different_accounts("유동자산", "비유동자산"))
        self.assertTrue(_different_accounts("부채", "유동부채"))
        self.assertFalse(_different_accounts("자 산 총 계", "자산총계"))
        self.assertTrue(_different_accounts("매출채권", "기타포괄손익"))

    def test_a_skipped_row_is_reported(self):
        rows = [row for row in SAMPLE.rows if row[0] != "비유동부채"]
        reading = self.read(rows)
        problems = " ".join(reading.statements[0].problems)
        self.assertIn("'24,210,425'를 AI가 읽지 않았다", problems)
        self.assertIn("'19,013,579'를 AI가 읽지 않았다", problems)

    def test_a_band_out_of_budget_is_asked_again_in_halves(self):
        from dart_review.documents.ai_reader import _State
        from PIL import Image

        class OnceTooLong:
            name = "scripted"

            def __init__(self):
                self.heights = []

            def transcribe(self, png, prompt):
                import io
                height = Image.open(io.BytesIO(png)).height
                self.heights.append(height)
                if len(self.heights) == 1:
                    raise VisionError("the model ran out of its output budget on one band")
                return f"줄 | {height:,}"

        model, state = OnceTooLong(), _State()
        answer = state.ask(model, Image.new("L", (300, 200), 255), "prompt", split=True)
        self.assertEqual(model.heights, [200, 120, 120])  # halves of 100 with 20 rows of overlap each
        self.assertEqual(answer, "줄 | 120\n줄 | 120")
        self.assertEqual(state.calls, 3)

    def test_the_notes_are_not_read_as_more_rows(self):
        from dart_review.documents.ai_reader import read_document
        notes = SampleStatement("주석", SAMPLE.company, SAMPLE.period_lines, "백만원", ["당기말", "전기말"],
                                [("보통예금", ["1,234,567", "1,111,111"])])
        model = ScriptedModel(SAMPLE.rows)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [SAMPLE, notes])
            reading = read_document(path, model)
        self.assertEqual(len(reading.statements), 1)
        self.assertEqual(len(reading.statements[0].rows), len(SAMPLE.rows))
        self.assertFalse(any("보통예금" in problem or "1,234,567" in problem for problem in reading.statements[0].problems))
        self.assertEqual(len(model.prompts), 1)  # the notes page cost no model call

    def test_a_label_printed_twice_keeps_both_rows_and_small_amounts_count(self):
        from dart_review.documents.ai_reader import read_document
        comprehensive = SampleStatement(
            "포괄손익계산서", SAMPLE.company, ["제 57 기 2025년 1월 1일부터 2025년 12월 31일까지"], "백만원",
            ["제 57 (당) 기", "제 56 (전) 기"],
            [("당기순이익", ["45,206,805", "34,451,351"]), ("관계기업 지분", ["92,804", "(71,581)"]),
             ("재측정요소", ["106,691", "(766,078)"]), ("관계기업 지분", ["244,161", "305,327"]),
             ("비지배지분의 증감", ["(973)", "(2,134)"]), ("총포괄손익", ["51,290,524", "51,296,338"])])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [comprehensive])
            reading = read_document(path, ScriptedModel(comprehensive.rows))
        statement = reading.statements[0]
        self.assertEqual([(row.label.replace(" ", ""), [row.amounts[c].printed for c in sorted(row.amounts)])
                          for row in statement.rows],
                         [(label.replace(" ", ""), amounts) for label, amounts in comprehensive.rows])
        self.assertEqual(self.flagged(reading), {})
        self.assertFalse([problem for problem in statement.problems if "읽지 않았다" in problem])

    def test_a_skipped_small_amount_is_reported(self):
        from dart_review.documents.ai_reader import read_document
        rows = [("자산총계", ["566,942,110", "514,531,948"]), ("비지배지분의 증감", ["(973)", "(2,134)"]),
                ("부채총계", ["130,621,773", "112,339,878"])]
        statement = SampleStatement("현금흐름표", SAMPLE.company, SAMPLE.period_lines, "백만원", SAMPLE.headers, rows)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [statement])
            reading = read_document(path, ScriptedModel([rows[0], rows[2]]))
        self.assertIn("'(973)'를 AI가 읽지 않았다", " ".join(reading.statements[0].problems))

    def test_two_statements_on_one_page_are_read_apart(self):
        from dart_review.documents.ai_reader import read_document
        income = [("매출", ["7,661,584", "7,926,651"]), ("당기순손실", ["(572,713)", "(937,643)"])]
        comprehensive = [("당기순손실", ["(572,713)", "(937,643)"]), ("기타포괄손익", ["15,606", "53,229"]),
                         ("총포괄손실", ["(557,107)", "(884,414)"])]
        rows = income + [("포괄손익계산서", ["", ""]), ("제 57 기 2025년 1월 1일부터 2025년 12월 31일까지", ["", ""]),
                         ("(단위: 백만원)", ["", ""]), ("과 목", ["제 57 (당) 기", "제 56 (전) 기"])] + comprehensive
        page = SampleStatement("손익계산서", SAMPLE.company, ["제 57 기 2025년 1월 1일부터 2025년 12월 31일까지"], "백만원",
                               SAMPLE.headers, rows)

        class InTurn:
            name = "scripted"

            def __init__(self, answers):
                self.answers = list(answers)

            def transcribe(self, png, prompt):
                lines = self.answers.pop(0)
                return "\n".join(f"{label} | {' | '.join(amounts)}" for label, amounts in lines)

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sample.pdf"
            text_pdf(path, [page])
            reading = read_document(path, InTurn([income, comprehensive]))
        first, second = reading.statements
        self.assertEqual((first.kind, [row.label for row in first.rows]), ("IS", ["매출", "당기순손실"]))
        self.assertEqual((second.kind, [row.label for row in second.rows]), ("CIS", ["당기순손실", "기타포괄손익", "총포괄손실"]))
        self.assertEqual(self.flagged(reading), {})

    def test_a_failed_band_is_reported_and_its_amounts_are_not_lost_silently(self):
        reading = self.read(SAMPLE.rows, fail=True)
        problems = " ".join(reading.statements[0].problems)
        self.assertIn("AI가 한 부분을 읽지 못했다", problems)
        self.assertIn("AI가 읽지 않았다", problems)


class PhotoEvidenceTests(unittest.TestCase):
    """The photo path (no text layer, OCR words only), on synthetic OCR tokens. Codex's review (D4) showed that a
    token anywhere in the band confirmed a number, labels were not compared, and two rows could merge."""

    def setUp(self):
        from dart_review.documents.statement import PeriodColumn, Statement
        self.statement = Statement("BS", True, "재무상태표", 1, 1, "원", [PeriodColumn("당기"), PeriodColumn("전기")], [], [])
        self.checks, self.claimed = [], {}

    def word(self, text, x0, top, method="ocr"):
        from dart_review.documents.words import Word
        return Word(text, 1, x0, x0 + 12 * len(text), top, top + 20, method, 95.0)

    def read(self, label, amounts, tokens, recent_from=0, reread=None):
        from dart_review.documents.ai_reader import Part, _add_row_by_tokens
        from dart_review.documents.vision import BandLine
        part = Part(1, None, [], "OCR", (0, 1000), list(tokens))
        _add_row_by_tokens(self.statement, self.checks, 0, BandLine(label, amounts), tokens, part, self.claimed,
                           recent_from, reread if reread is not None else set())
        return part

    def flags(self, label):
        rows = [index for index, row in enumerate(self.statement.rows) if row.label == label]
        return [reason for check in self.checks if check.row in rows for reason in check.reasons]

    def test_a_row_confirmed_on_its_own_line_with_its_label(self):
        tokens = [self.word("매출채권", 50, 100), self.word("1,000", 400, 100), self.word("2,000", 600, 100)]
        self.read("매출채권", ["1,000", "2,000"], tokens)
        self.assertEqual([(c.status, c.evidence) for c in self.checks], [("검사 통과", "OCR")] * 2)

    def test_two_rows_of_the_same_label_and_value_in_two_bands_stay_two(self):
        # Codex's case: they once merged into one row, and the second OCR token was left unclaimed
        first = [self.word("매출액", 50, 100), self.word("1,000", 400, 100)]
        second = [self.word("매출액", 50, 140), self.word("1,000", 400, 140)]
        self.read("매출액", ["1,000"], first)
        reread = set()  # the next band covers both lines: the model re-reads the first and reads the second
        self.read("매출액", ["1,000"], first + second, recent_from=0, reread=reread)
        self.read("매출액", ["1,000"], first + second, recent_from=0, reread=reread)
        self.assertEqual(len(self.statement.rows), 2)
        self.assertEqual([c.evidence for c in self.checks], ["OCR", "OCR"])

    def test_the_same_token_read_again_in_the_overlap_is_the_same_row(self):
        tokens = [self.word("매출액", 50, 100), self.word("1,000", 400, 100), self.word("2,000", 600, 100)]
        self.read("매출액", ["1,000", "2,000"], tokens)
        self.read("3 매출액", ["1,000", "2,000"], tokens, recent_from=0, reread=set())  # re-read, another label
        self.assertEqual(len(self.statement.rows), 1)

    def test_numbers_from_two_lines_are_marked(self):
        tokens = [self.word("1,000", 400, 100), self.word("2,000", 600, 160)]
        self.read("매출액", ["1,000", "2,000"], tokens)
        self.assertTrue(any("한 줄에서 찾지 못했다" in reason for reason in self.flags("매출액")))

    def test_a_label_the_ocr_reads_differently_is_marked(self):
        # the photo case: the model wrote "부채" for the line OCR reads as "유동부채"
        tokens = [self.word("1.", 30, 100), self.word("유동부채", 50, 100), self.word("106,411,348", 400, 100)]
        self.read("부채", ["106,411,348"], tokens)
        self.assertTrue(any("OCR이 읽은 계정명 '유동부채'" in reason for reason in self.flags("부채")), self.flags("부채"))

    def test_a_label_the_ocr_could_not_read_is_unverified_not_confirmed(self):
        tokens = [self.word("1,000", 400, 100)]
        self.read("매출액", ["1,000"], tokens)
        self.assertEqual(self.checks[0].evidence, "OCR (숫자만, 계정명 미확인)")

    def test_ocr_amounts_the_model_skipped_are_reported(self):
        from dart_review.documents.ai_reader import _report_unread_tokens
        tokens = [self.word("매출액", 50, 100), self.word("1,000", 400, 100),
                  self.word("재고자산", 50, 140), self.word("7,953,586", 400, 140), self.word("7,953,586", 401, 141)]
        part = self.read("매출액", ["1,000"], tokens)
        _report_unread_tokens(self.statement, part, self.claimed)
        self.assertEqual(self.statement.problems, ["1쪽: OCR이 읽은 금액 '7,953,586'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)"])


if __name__ == "__main__":
    unittest.main()
