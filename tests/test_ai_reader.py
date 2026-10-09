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

    def test_a_failed_band_is_reported_and_its_amounts_are_not_lost_silently(self):
        reading = self.read(SAMPLE.rows, fail=True)
        problems = " ".join(reading.statements[0].problems)
        self.assertIn("AI가 한 부분을 읽지 못했다", problems)
        self.assertIn("AI가 읽지 않았다", problems)


if __name__ == "__main__":
    unittest.main()
