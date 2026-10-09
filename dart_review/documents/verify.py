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
    evidence: str = ""  # AI reading: what confirmed the value ("PDF 글자", "OCR"), empty when nothing did

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


# balance-sheet identities: total = the sum of parts (labels compared without spaces)
IDENTITIES = (("자산총계", ("부채총계", "자본총계")), ("자산총계", ("유동자산", "비유동자산")),
              ("부채총계", ("유동부채", "비유동부채")), ("자산총계", ("부채와자본총계",)))


def _balance(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> list[str]:
    """Check every identity whose rows are all present; return the names of the identities checked."""
    if statement.kind != "BS":
        return []
    index: dict[str, int] = {}
    for r_index, row in enumerate(statement.rows):
        key = re.sub(r"\s+", "", row.label)
        index.setdefault(key, r_index)
    checked = []
    for total, parts in IDENTITIES:
        names = (total, *parts)
        if not all(name in index for name in names):
            continue
        rule = f"{total} = {' + '.join(parts)}"
        checked.append(rule)
        for column in range(len(statement.columns)):
            cells = {name: statement.rows[index[name]].amounts.get(column) for name in names}
            if any(cell is None or cell.value is None for cell in cells.values()):
                continue
            if cells[total].value != sum(cells[part].value for part in parts):
                for name in names:
                    if (index[name], column) in by_cell:
                        by_cell[(index[name], column)].flag(f"{rule}가 맞지 않는다 (어느 칸이 틀렸는지는 모른다)")
    return checked
