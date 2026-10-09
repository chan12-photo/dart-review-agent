"""Read financial statements out of lines: title, unit, period columns, and one row per account.

Only what the page says is used: the statement title, the unit line ("단위: 원/천원/백만원"), the column
headers ("제 56(당) 기", "당기", "2025년"), and the period lines near the title ("제 56 기 2025년 1월 1일부터
2025년 12월 31일까지"). An amount keeps its printed text next to its value in 원, so every value can be traced.
Nothing is guessed: a column whose period cannot be read keeps its header text and no year.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import re
from typing import Sequence

from ..accounts import ACCOUNTS, normalize_name
from .table import Cell, Column, Line, number_columns

TITLES = {"재무상태표": "BS", "대차대조표": "BS", "포괄손익계산서": "CIS", "손익계산서": "IS", "현금흐름표": "CF",
          "자본변동표": "SCE"}
UNITS = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}
_TITLE = re.compile(r"^(연결\s*)?(" + "|".join(sorted(TITLES, key=len, reverse=True)) + r")$")
_UNIT = re.compile(r"단위\s*[:：]?\s*(백만원|천원|억원|원)")
_ORDINAL = re.compile(r"제\s*(\d+)\s*(?:\(\s*(당|전|전전)\s*\))?\s*기")
_PERIOD_LINE = re.compile(r"제\s*(\d+)\s*(?:\([^)]*\))?\s*기.*?(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*(?:현재|까지)")
_YEAR = re.compile(r"(\d{4})\s*(?:년|\.)")
# an item index before a label; OCR reads a Roman numeral "Ⅰ." as "|." or "I." too
_INDEX = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*\.?|[|IVXlivx]{1,4}\s*\.|\d{1,2}\.|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*")
_NOTE = re.compile(r"\s*\(?\s*주\s*[\d,\s]+\)?\s*$")  # a note reference after a label: "현금 (주4,5)"


@dataclass
class Amount:
    cell: Cell
    value: int | None  # in 원; None for a dash (nothing reported)
    printed: str
    column: int


@dataclass
class Row:
    label: str  # as printed, index and note reference removed
    account: str | None  # one of the tool's six accounts when the label is one of its names
    label_cell: Cell | None
    amounts: dict[int, Amount] = field(default_factory=dict)
    unplaced: int = 0  # number-like cells on the same line that fit no column: the row's structure is in doubt


@dataclass
class PeriodColumn:
    header: str
    ordinal: int | None = None  # 기수 ("제 56 기")
    year: int | None = None
    end: str | None = None  # the period end (YYYY-MM-DD) when a period line states it


@dataclass
class Statement:
    kind: str  # BS, IS, CIS, CF, SCE
    consolidated: bool | None
    title: str
    page: int
    unit: int | None  # 원 per printed unit; None when no unit line was found
    unit_text: str | None
    columns: list[PeriodColumn]
    rows: list[Row]
    problems: list[str] = field(default_factory=list)


def parse_amount(printed: str, unit: int | None) -> int | None:
    """The value in 원 of an amount as printed, or None for a dash. Raises ValueError when it is not an amount.

    "(1,234)", "△1,234", "-1,234" are negative. Separators are removed here; whether they were plausible is
    judged in verify.py, so a misread "300,870.903" is not silently accepted there.
    """
    text = printed.replace(" ", "").replace("（", "(").replace("）", ")").replace("−", "-")
    if text in ("-", "–", "—"):
        return None
    negative = text.startswith("(") and text.endswith(")") or text[:1] in "△▲-"
    digits = re.sub(r"[()△▲\-,.]", "", text)
    if not digits.isdigit():
        raise ValueError(f"not an amount: {printed!r}")
    value = int(digits) * (unit or 1)
    return -value if negative else value


def clean_label(text: str, ocr: bool = False) -> str:
    label = re.sub(r"\s+", " ", _NOTE.sub("", _INDEX.sub("", text)).strip())
    if ocr:  # stray marks OCR puts before a label ("| 유동자산", "© 비유동자산")
        label = _INDEX.sub("", re.sub(r"^[^\w가-힣(]+", "", label)).strip()
    if ocr:  # OCR splits Hangul syllables of one word ("자 산 총계"); statement labels rarely need those spaces
        label = re.sub(r"(?<=[가-힣]) (?=[가-힣(])|(?<=[가-힣(]) (?=[가-힣)])", "", label)
    return label


def account_of(label: str) -> str | None:
    """The tool's account for a label, by the names it already uses (accounts.py); other labels have none."""
    key = normalize_name(label)
    for account in ACCOUNTS.values():
        if key in {normalize_name(name) for name in account.names}:
            return account.key
    return None


def find_statements(lines: Sequence[Line]) -> list[Statement]:
    """Each statement title starts a block that ends at the next title; the block's rows are read in turn."""
    starts = [index for index, line in enumerate(lines) if _TITLE.match(re.sub(r"\s+", "", line.text))]
    statements = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        statements.append(read_statement(lines[start], lines[start + 1:end], lines[max(0, start - 3):end]))
    return statements


def read_statement(title_line: Line, body: Sequence[Line], context: Sequence[Line]) -> Statement:
    compact = re.sub(r"\s+", "", title_line.text)
    match = _TITLE.match(compact)
    kind = TITLES[match.group(2)]
    unit_text = next((found.group(1) for line in context if (found := _UNIT.search(line.text.replace(" ", "")))), None)
    unit = UNITS.get(unit_text) if unit_text else None
    problems = [] if unit else ["단위 줄을 찾지 못해 금액 단위를 알 수 없다"]
    height = sorted(cell.bottom - cell.top for line in body for cell in line.cells)
    tolerance = 2.0 * (height[len(height) // 2] if height else 10.0)
    columns = number_columns(body, tolerance)
    periods = _period_columns(body, columns, tolerance, context)
    columns, periods = _merge_nested(body, columns, periods, context)
    rows = []
    orphans = 0  # amounts on the page that end up in no row: a broken table, never silently dropped
    for line in body:
        amounts = {}
        label_cells = []
        for cell in line.cells:
            index = next((i for i, column in enumerate(columns) if column.holds(cell, tolerance)), None)
            if index is not None and columns[index].header.isdigit():  # merged under a period heading
                index = int(columns[index].header)
            if cell.is_amount and index is not None and index < len(periods) and not _is_note_column(periods[index]):
                try:
                    amounts[index] = Amount(cell, parse_amount(cell.text, unit), cell.text, index)
                except ValueError:
                    label_cells.append(cell)
            elif index is None:
                label_cells.append(cell)
        line_amounts = [cell for cell in line.cells if cell.is_amount and not _is_dash(cell.text)]
        if not amounts or not label_cells:
            orphans += len([cell for cell in line_amounts if not _is_note_like(cell, columns, periods, tolerance)])
            continue
        label_cell = label_cells[0]
        label = clean_label(label_cell.text, ocr=label_cell.method == "ocr")
        if not label:
            orphans += len(amounts)
            continue
        unplaced = len([cell for cell in line_amounts if all(cell is not item.cell for item in amounts.values())
                        and not _is_note_like(cell, columns, periods, tolerance)])
        orphans += unplaced
        rows.append(Row(label, account_of(label), label_cell, amounts, unplaced))
    if kind == "BS" and not {"자산총계", "부채총계", "자본총계"} <= {re.sub(r"\s+", "", row.label) for row in rows}:
        problems.append("자산총계·부채총계·자본총계 줄을 모두 찾지 못해 합계 검산을 하지 못했다")
    empty = [row.label for row in rows for index, period in enumerate(periods)
             if index not in row.amounts and not _is_note_column(period)]
    if empty:
        problems.append(f"빈 칸 {len(empty)}개 ({', '.join(dict.fromkeys(empty))}): 원본이 '-'(해당 없음)인지, "
                        "읽지 못한 숫자인지 확인 필요")
    if orphans:
        problems.append(f"표에 넣지 못한 금액 {orphans}개: 줄이나 열을 복원하지 못한 행이 있을 수 있다 (원본과 대조 필요)")
    return Statement(kind, compact.startswith("연결"), compact, title_line.page, unit, unit_text, periods, rows, problems)


def _is_dash(text: str) -> bool:
    return text.strip() in ("-", "–", "—")


def _is_note_like(cell: Cell, columns: list[Column], periods: list[PeriodColumn], tolerance: float) -> bool:
    """A number in the note column (주석) or a short number in a header line is not a missing amount."""
    if re.fullmatch(r"\d{1,2}(\s*,\s*\d{1,2})*", cell.text.strip()):
        return True  # note references: "8", "4, 29", "4,5,7,29" (amounts group their digits by three)
    index = next((i for i, column in enumerate(columns) if column.holds(cell, tolerance)), None)
    if index is not None and columns[index].header.isdigit():
        return False
    if index is not None and index < len(periods) and _is_note_column(periods[index]):
        return True
    return len(re.sub(r"\D", "", cell.text)) <= 2


def _merge_nested(body: Sequence[Line], columns: list[Column], periods: list[PeriodColumn],
                  context: Sequence[Line]) -> tuple[list[Column], list[PeriodColumn]]:
    """Audit reports print a period's details and subtotals in two positions under one heading ("제 57 (당) 기").
    When a header line has two or more period headings, each number column joins the heading nearest to it
    (the note column stays out), so a period is one column of values whatever its print position."""
    headings = []
    for line in body:
        if any(cell.is_amount and len(re.sub(r"\D", "", cell.text)) >= 4 for cell in line.cells):
            break
        found = [cell for cell in line.cells if _ORDINAL.search(cell.text) or re.search(r"(당|전)\s*기", cell.text)]
        if len(found) >= 2:
            headings = found
    if len(headings) < 2:
        return columns, periods
    ends = {}
    for line in context:
        for match in _PERIOD_LINE.finditer(line.text):
            ordinal, year, month, day = (int(value) for value in match.groups())
            ends[ordinal] = (year, f"{year:04d}-{month:02d}-{day:02d}")
    centres = [(cell.x0 + cell.x1) / 2 for cell in headings]
    bounds = [(a + b) / 2 for a, b in zip(centres, centres[1:])]
    merged: list[Column] = []
    for column, period in zip(columns, periods):
        if _is_note_column(period):
            continue
        index = sum(column.right > bound for bound in bounds)
        merged.append(Column(column.right, header=str(index)))
    new_periods = []
    for cell in headings:
        found = _ORDINAL.search(cell.text)
        number = int(found.group(1)) if found else None
        year, end = ends.get(number, (None, None)) if number else (None, None)
        new_periods.append(PeriodColumn(cell.text, number, year, end))
    return merged, new_periods


def _is_note_column(column: PeriodColumn) -> bool:
    return column.header.replace(" ", "") in ("주석", "주")


def _period_columns(body: Sequence[Line], columns: list[Column], tolerance: float,
                    context: Sequence[Line]) -> list[PeriodColumn]:
    """Each number column's header: the text right above its first amount, read for a 기수 and a year."""
    ends = {}
    for line in context:
        for found in _PERIOD_LINE.finditer(line.text):
            ordinal, year, month, day = (int(value) for value in found.groups())
            ends[ordinal] = (year, f"{year:04d}-{month:02d}-{day:02d}")
    result = []
    for column in columns:
        parts = []  # a header may take two lines ("제 56(당) 기" over "금 액"); unit and period lines are not headers
        for line in body:
            amounts = [cell for cell in line.cells if cell.is_amount and column.holds(cell, tolerance)]
            if amounts:
                break
            if _UNIT.search(line.text.replace(" ", "")) or _PERIOD_LINE.search(line.text):
                parts = []  # the header is below the unit and period lines; what is above them is not
                continue
            texts = [cell.text for cell in line.cells if not cell.is_amount
                     and cell.x0 - tolerance <= column.right and cell.x1 >= column.right - 6 * tolerance]
            if texts:
                parts.append(" ".join(texts))
        header = " ".join(parts)
        ordinal_match = _ORDINAL.search(header)
        ordinal = int(ordinal_match.group(1)) if ordinal_match else None
        year_match = _YEAR.search(header)
        year, end = (ends[ordinal] if ordinal in ends else (int(year_match.group(1)) if year_match else None, None))
        result.append(PeriodColumn(header.strip(), ordinal, year, end))
    return result


def value_in_won(amount: Amount) -> Decimal | None:
    return None if amount.value is None else Decimal(amount.value)
