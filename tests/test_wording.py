"""The visible answer speaks politely even though tool notes and reasons are terse data (v0.1.x)."""

import ast
from pathlib import Path
import unittest

from dart_review.render import clarifying_question, polite

ROOT = Path(__file__).resolve().parents[1]
# modules whose string literals become tool notes or reasons shown after "참고:" or "이유:"
NOTE_SOURCES = ("compare.py", "periods.py", "review.py", "tools.py")


def terse_literals():
    """Every string (or f-string text part) in those modules that ends a clause in the terse 다 style."""
    found = []
    for name in NOTE_SOURCES:
        tree = ast.parse((ROOT / "dart_review" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = node.value.strip()
                if text.endswith(")") and " (" in text:
                    text = text[: text.rindex(" (")]
                if text.endswith("다") and not text.endswith("니다") and any("가" <= c <= "힣" for c in text):
                    found.append((name, node.value))
    return found


class PoliteWordingTests(unittest.TestCase):
    def test_known_notes(self):
        cases = {
            "이후 보고서의 재작성 여부는 확인하지 않았다 (2026년 사업보고서를 쓸 수 없음)":
                "이후 보고서의 재작성 여부는 확인하지 않았습니다 (2026년 사업보고서를 쓸 수 없음)",
            "통화가 다르다 (KRW, USD)": "통화가 다릅니다 (KRW, USD)",
            "x 기준은 합치거나 비교하지 않는다 (나란히 보여줄 수만 있다)": "x 기준은 합치거나 비교하지 않습니다 (나란히 보여줄 수만 있습니다)",
            "a (이 비교는 같은 보고서의 값을 쓴다)": "a (이 비교는 같은 보고서의 값을 씁니다)",
            "삼성은 개발 중 조회하지 않는 평가용 회사다": "삼성은 개발 중 조회하지 않는 평가용 회사입니다",
            "2025-07-01~2025-09-30 (3개월) 값이 없다": "2025-07-01~2025-09-30 (3개월) 값이 없습니다",
            "매출액 칸이 없음": "매출액 칸이 없음",  # noun-style notes stay as they are
        }
        for terse, expected in cases.items():
            self.assertEqual(polite(terse), expected)

    def test_every_terse_literal_in_note_sources_becomes_polite(self):
        literals = terse_literals()
        self.assertGreater(len(literals), 20)  # the scan really sees the note and reason texts
        for name, literal in literals:
            with self.subTest(module=name, literal=literal):
                text = polite(literal.strip())
                head = text[: text.rindex(" (")] if text.endswith(")") and " (" in text else text
                self.assertTrue(head.endswith("니다"), text)

    def test_account_question_does_not_assume_a_comparison(self):
        for accounts in (["operating_income", "net_income"], []):
            question = clarifying_question(accounts)
            self.assertNotIn("비교", question)
        self.assertEqual(clarifying_question(["operating_income", "net_income"]),
                         "영업이익과 당기순이익 중 어느 것을 말씀하신 건가요?")


if __name__ == "__main__":
    unittest.main()
