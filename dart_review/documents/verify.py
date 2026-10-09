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
        _subtotals(statement, by_cell)
        checks += by_cell.values()
    return checks


def _subtotals(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> int:
    """Check every subtotal against the detail rows under it; return how many subtotals were checked.

    Statements print detail items and subtotals in two positions within one period ("겹친 금액 열"): the details
    left, the subtotals right. Within a run of rows on one page part, the amounts' x centres of a period split
    into those two groups at the widest gap (when it is wider than three character heights). A subtotal row is
    then followed by its detail rows until the next subtotal; their sum must equal it. A failure marks the
    subtotal and every detail cell, because which one is wrong cannot be known. This is what catches a digit
    misread the same way by the model and by OCR (7,953,586 read as 7,963,586 on a photo).
    """
    checked = 0
    for column in range(len(statement.columns)):
        placed = []  # (row index, amount, x centre, height, segment)
        segment, last = 0, None
        for r_index, row in enumerate(statement.rows):
            amount = row.amounts.get(column)
            if amount is None or amount.value is None or amount.cell.method == "ai":
                continue
            cell = amount.cell
            centre = (cell.x0 + cell.x1) / 2
            if last is not None and (cell.page != last[0] or abs(centre - last[1]) > 8 * max(cell.bottom - cell.top, 1)):
                segment += 1  # another page, or the other half of a photographed spread
            last = (cell.page, centre)
            placed.append((r_index, amount, centre, cell.bottom - cell.top, segment))
        levels: dict[int, int] = {}
        for seg in {item[4] for item in placed}:
            items = [item for item in placed if item[4] == seg]
            xs = sorted(item[2] for item in items)
            gaps = [(b - a, (a + b) / 2) for a, b in zip(xs, xs[1:])]
            if not gaps:
                continue
            widest, cut = max(gaps)
            if widest < 3 * median_height([item[3] for item in items]):
                continue
            for item in items:
                levels[item[0]] = 1 if item[2] > cut else 2  # 1 = subtotal position, 2 = detail position
        for r_index in range(len(statement.rows)):
            if levels.get(r_index) != 1:
                continue
            details, known = [], True
            for following in range(r_index + 1, len(statement.rows)):
                if levels.get(following) == 1:
                    break
                if following not in levels:
                    # a row under this subtotal whose amount has no position (read by the AI only, or missing):
                    # the sum cannot be checked, and an unknown is not called a mismatch
                    if column in statement.rows[following].amounts or not statement.rows[following].amounts:
                        known = False
                    continue
                details.append(following)
            if not known or len(details) < 2:
                continue
            checked += 1
            total = statement.rows[r_index].amounts[column].value
            if total != sum(statement.rows[d].amounts[column].value for d in details):
                label = statement.rows[r_index].label
                for target in [r_index, *details]:
                    if (target, column) in by_cell:
                        by_cell[(target, column)].flag(f"소계 '{label}'와 그 아래 항목의 합이 맞지 않는다 (어느 칸이 틀렸는지는 모른다)")
    return checked


def median_height(heights: list[float]) -> float:
    ordered = sorted(heights)
    return ordered[len(ordered) // 2] if ordered else 1.0


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
