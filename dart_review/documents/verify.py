"""Checks that mark a cell "확인 필요" instead of trusting it. Nothing is corrected.

A misread amount that looks like an amount is the dangerous case (OCR read "300,870,903" as "300,870.903"
in our first test). The checks: separators in the places a Korean statement puts them, no separator where
the document otherwise uses them, a low OCR confidence, and the balance-sheet identity
자산총계 = 부채총계 + 자본총계 in each column. A failed identity marks all three cells, because which one is
wrong cannot be known from the page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable

from .statement import Amount, Statement

OCR_CONFIDENCE = 85.0  # Tesseract's 0-100 score; below this a cell is checked by a person
_GROUPED = re.compile(r"^\d{1,3}(,\d{3})+$")
_SIGNS = re.compile(r"[()（）△▲\-−\s]")

REVIEW, CHECKED = "확인 필요", "검사 통과"


@dataclass
class CellCheck:
    statement: int  # index in the statement list
    row: int
    column: int
    status: str = CHECKED
    reasons: list[str] = field(default_factory=list)

    def flag(self, reason: str) -> None:
        self.status = REVIEW
        if reason not in self.reasons:
            self.reasons.append(reason)


def digits_of(printed: str) -> str:
    return _SIGNS.sub("", printed)


def separator_problem(printed: str) -> str | None:
    digits = digits_of(printed)
    if digits in ("", "-", "–", "—"):
        return None
    if "." in digits:
        return "금액에 마침표가 있다 (쉼표를 잘못 읽었을 수 있다)"
    if "," in digits and not _GROUPED.match(digits):
        return "쉼표 위치가 세 자리 단위가 아니다"
    return None


def uses_separators(amounts: Iterable[Amount]) -> bool:
    """Whether the document groups long amounts with commas (most amounts of four or more digits do)."""
    long = [digits_of(amount.printed) for amount in amounts if len(re.sub(r"\D", "", amount.printed)) >= 4]
    return bool(long) and sum("," in digits for digits in long) / len(long) >= 0.8


def check(statements: list[Statement]) -> list[CellCheck]:
    everything = [amount for statement in statements for row in statement.rows for amount in row.amounts.values()]
    grouped = uses_separators(everything)
    checks = []
    for s_index, statement in enumerate(statements):
        by_cell: dict[tuple[int, int], CellCheck] = {}
        for r_index, row in enumerate(statement.rows):
            for c_index, amount in row.amounts.items():
                result = CellCheck(s_index, r_index, c_index)
                problem = separator_problem(amount.printed)
                if problem:
                    result.flag(problem)
                elif grouped and len(re.sub(r"\D", "", amount.printed)) >= 5 and "," not in amount.printed:
                    result.flag("다른 금액과 달리 쉼표가 없다 (쉼표를 놓쳤을 수 있다)")
                confidence = amount.cell.confidence
                if confidence is not None and confidence < OCR_CONFIDENCE:
                    result.flag(f"OCR 확신도가 낮다 ({confidence:.0f})")
                if statement.unit is None:
                    result.flag("금액 단위를 알 수 없다")
                if row.unplaced:
                    result.flag("같은 줄에 열을 정하지 못한 숫자가 있다 (줄 구조가 깨졌을 수 있다)")
                by_cell[(r_index, c_index)] = result
        _balance(statement, by_cell)
        checks += by_cell.values()
    return checks


def _balance(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> None:
    if statement.kind != "BS":
        return
    index = {}
    for r_index, row in enumerate(statement.rows):
        key = re.sub(r"\s+", "", row.label)
        if key in ("자산총계", "부채총계", "자본총계") and key not in index:
            index[key] = r_index
    if len(index) < 3:
        return
    for column in range(len(statement.columns)):
        cells = {key: statement.rows[r].amounts.get(column) for key, r in index.items()}
        if any(cell is None or cell.value is None for cell in cells.values()):
            continue
        if cells["자산총계"].value != cells["부채총계"].value + cells["자본총계"].value:
            for key, r in index.items():
                by_cell[(r, column)].flag("자산총계 = 부채총계 + 자본총계가 맞지 않는다 (세 칸 중 어느 것이 틀렸는지 모른다)")
