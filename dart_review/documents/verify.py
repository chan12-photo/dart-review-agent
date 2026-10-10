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

from .statement import PERIOD_MARK, Amount, Statement

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
    return _SIGNS.sub("", re.sub(r"\s*(백만|천)?원$", "", printed))


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
                if c_index < len(statement.columns) and not PERIOD_MARK.search(statement.columns[c_index].header or ""):
                    result.flag("이 열의 기간 머리글(제 N 기, 당기·전기, 연도)을 확인하지 못했다")
                if row.unplaced:
                    result.flag("같은 줄에 열을 정하지 못한 숫자가 있다 (줄 구조가 깨졌을 수 있다)")
                by_cell[(r_index, c_index)] = result
        check_sums(statement, by_cell)
        checks += by_cell.values()
    return checks


SUMS_KINDS = ("BS", "CF", "RE")  # statements whose subtotals are plain sums (income statements are not)


def check_sums(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> None:
    """The balance identities and the subtotals; how many were checked is kept on the statement, and a
    statement where none could be is reported (a sum that was not checked is not a sum that held)."""
    if statement.kind not in SUMS_KINDS:
        return
    identities = _balance(statement, by_cell)
    subtotals = _subtotals(statement, by_cell)
    statement.sums_checked = len(identities) + subtotals  # each computed in one period
    if statement.kind == "BS" and not identities and not any("합계 검산" in problem for problem in statement.problems):
        statement.problems.append("합계 줄을 찾지 못해 재무상태표 항등식(자산총계 = 부채총계 + 자본총계 등)을 검산하지 못했다")
    if not subtotals:
        statement.problems.append("소계와 그 아래 항목을 구분하지 못해 소계 검산을 하지 못했다")


def _subtotals(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> int:
    """Check every subtotal against the detail rows under it; return how many sums were checked.

    Statements print detail items and subtotals in two positions within one period ("겹친 금액 열"): the details
    left, the subtotals right. Within a run of rows on one page part, the amounts' x centres of a period split
    into those two groups at the widest gap (when it is wider than three character heights). A subtotal row is
    then followed by its detail rows until the next subtotal.

    A detail may itself be the sum of the details after it, printed in the same position (현금흐름표: 영업에서
    창출된 현금흐름 = 당기순이익 + 조정 + 자산부채의 변동). That is recognised only from the labels' structure,
    their item marker ("1." over "가.") and indentation, never because the numbers happen to add up: an
    earlier rule that folded any detail equal to the sum of the next ones could hide a wrong cell. The subtotal
    must equal the sum of its top-level details, and each inner parent the sum of its own children.

    A failure marks the sum and every cell in it, because which one is wrong cannot be known. This is what
    catches a digit misread the same way by the model and by OCR (7,953,586 read as 7,963,586 on a photo).
    """
    checked = 0
    if statement.kind in ("IS", "CIS"):
        return 0  # expenses are printed without a sign, so a subtotal is not the plain sum of the rows near it
    for column in range(len(statement.columns)):
        placed = []  # (row index, amount, right edge, height, segment)
        segment, last = 0, None
        for r_index, row in enumerate(statement.rows):
            amount = row.amounts.get(column)
            if amount is None or amount.cell.method == "ai":
                continue  # a dash ("-", nothing) is kept: it is a printed zero with a position
            cell = amount.cell
            right = cell.x1  # amounts are right-aligned: one print position shares its right edge
            # another page, or the other half of a photographed spread (about 55 character heights away; the
            # detail and subtotal positions of one period are about 10 apart, so they stay in one segment)
            if last is not None and (cell.page != last[0] or abs(right - last[1]) > 20 * max(cell.bottom - cell.top, 1)):
                segment += 1
            last = (cell.page, right)
            placed.append((r_index, amount, right, cell.bottom - cell.top, segment))
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
        subtotals = [index for index in range(len(statement.rows)) if levels.get(index) == 1]
        for position, r_index in enumerate(subtotals):
            if _is_closing_total(statement.rows[r_index].label):
                # a closing total (자본총계) comes after its details; it takes the rows since the previous
                # subtotal only when that one is a closing total too (otherwise they are that subtotal's details)
                previous = subtotals[position - 1] if position else -1
                if previous >= 0 and not _is_closing_total(statement.rows[previous].label):
                    continue
                span = range(previous + 1, r_index)
            else:
                # a section heading (Ⅰ. 유동자산) comes before its details, up to the next subtotal
                span = range(r_index + 1, subtotals[position + 1] if position + 1 < len(subtotals) else len(statement.rows))
            details, known = [], True
            for following in span:
                if following not in levels:
                    # a row under this subtotal whose amount has no position (read by the AI only, or missing):
                    # the sum cannot be checked, and an unknown is not called a mismatch
                    if column in statement.rows[following].amounts or not statement.rows[following].amounts:
                        known = False
                    continue
                details.append(following)
            if not known or len(details) < 2:
                continue
            checked += _check_sum(statement, by_cell, column, r_index, details)
    return checked


def _is_closing_total(label: str) -> bool:
    return bool(re.search(r"(총계|합계)$|^부채와자본", re.sub(r"\s+", "", label)))


def _check_sum(statement: Statement, by_cell: dict[tuple[int, int], CellCheck], column: int, parent: int,
               details: list[int]) -> int:
    """``parent`` against ``details``; returns the number of sums checked.

    - Item markers that differ among the details ("1." over "가.") give the structure: the parent equals the sum
      of its top-level details, and each detail with children (deeper markers) is checked against them.
    - Otherwise every detail is a direct part: the plain sum must hold. If it fails but would hold were some
      detail the sum of the ones after it (shown only by indentation, or only by the numbers), a third level
      cannot be told from a wrong cell: the sum is not counted as checked, and its cells are marked.
    """
    def value(index: int) -> int:
        return statement.rows[index].amounts[column].value or 0  # a dash is zero

    markers = [_marker(statement.rows[index]) for index in details]
    if None not in markers and len(set(markers)) > 1:
        top = _levels(details, markers)
    else:
        top = [(index, []) for index in details]
        if value(parent) != sum(value(index) for index in details):
            indents = [_indent(statement.rows[index]) for index in details]
            nested = _levels(details, indents) if None not in indents and max(indents) - min(indents) > 1.0 else None
            explained = (nested is not None and value(parent) == sum(value(index) for index, _ in nested)) or \
                _sums_by_coincidence(value(parent), [value(index) for index in details])
            if explained:
                label = statement.rows[parent].label
                note = (f"소계 '{label}'는 세부 항목의 층(어느 항목이 다른 항목의 합인지)을 표에서 확인하지 못해 검산하지 못했다 "
                        "(들여쓰기나 숫자로는 맞지만 항목 기호가 없다)")
                if note not in statement.problems:
                    statement.problems.append(note)
                for target in [parent, *details]:
                    if (target, column) in by_cell:
                        by_cell[(target, column)].flag(
                            f"소계 '{label}'와 세부 항목의 합이 그대로는 맞지 않는다. 일부 항목이 다른 항목의 합일 수 있지만 "
                            "표에서 확인하지 못했다")
                return 0
    if value(parent) != sum(value(index) for index, _ in top):
        _flag_sum(statement, by_cell, column, parent, [index for index, _ in top])
    checked = 1
    for index, children in top:
        if children:
            checked += _check_sum(statement, by_cell, column, index, children)
    return checked


def _levels(details: list[int], depths: list[float]) -> list[tuple[int, list[int]]]:
    """(detail, its children): a detail's children are the details after it that sit deeper."""
    top, position = [], 0
    while position < len(details):
        end = position + 1
        while end < len(details) and depths[end] > depths[position] + 1e-6:
            end += 1
        top.append((details[position], details[position + 1:end]))
        position = end
    return top


def _sums_by_coincidence(total: int, values: list[int]) -> bool:
    """Whether ``total`` is the sum of ``values`` once some value is taken to stand for the values right after
    it (that value equals their sum)."""
    folded, index = [], 0
    while index < len(values):
        folded.append(values[index])
        end = next((j for j in range(index + 2, len(values)) if values[index] == sum(values[index + 1:j + 1])), None)
        index = (end if end is not None else index) + 1
    return len(folded) < len(values) and total == sum(folded)


def _flag_sum(statement: Statement, by_cell: dict[tuple[int, int], CellCheck], column: int, parent: int,
              parts: list[int]) -> None:
    label = statement.rows[parent].label
    for target in [parent, *parts]:
        if (target, column) in by_cell:
            by_cell[(target, column)].flag(f"소계 '{label}'와 그 아래 항목의 합이 맞지 않는다 (어느 칸이 틀렸는지는 모른다)")


_MARKERS = ((re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4})\s*\."), 1), (re.compile(r"^\s*\d{1,2}\s*\."), 2),
            (re.compile(r"^\s*[가-하]\s*\."), 3), (re.compile(r"^\s*\(\s*\d{1,2}\s*\)"), 4),
            (re.compile(r"^\s*[①-⑳]"), 5))


def _marker(row) -> int | None:
    """The depth its item marker gives a row's label (Ⅰ. > 1. > 가. > (1) > ① > none); None without a label."""
    cell = row.label_cell
    if cell is None:
        return None
    return next((rank for pattern, rank in _MARKERS if pattern.match(cell.text)), 6)


def _indent(row) -> float | None:
    cell = row.label_cell
    return None if cell is None else round(cell.x0, 1)


def median_height(heights: list[float]) -> float:
    ordered = sorted(heights)
    return ordered[len(ordered) // 2] if ordered else 1.0


# balance-sheet identities: total = the sum of parts (labels compared without spaces)
IDENTITIES = (("자산총계", ("부채총계", "자본총계")), ("자산총계", ("유동자산", "비유동자산")),
              ("부채총계", ("유동부채", "비유동부채")), ("자산총계", ("부채와자본총계",)))


def _balance(statement: Statement, by_cell: dict[tuple[int, int], CellCheck]) -> list[str]:
    """Check every identity whose rows and values are present; return one entry per identity and period
    actually computed."""
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
        for column in range(len(statement.columns)):
            cells = {name: statement.rows[index[name]].amounts.get(column) for name in names}
            if any(cell is None or cell.value is None for cell in cells.values()):
                continue  # not computed in this period: not counted
            checked.append(f"{rule} ({column})")
            if cells[total].value != sum(cells[part].value for part in parts):
                for name in names:
                    if (index[name], column) in by_cell:
                        by_cell[(index[name], column)].flag(f"{rule}가 맞지 않는다 (어느 칸이 틀렸는지는 모른다)")
    return checked
