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
from .table import UNIT_SUFFIX, Cell, Column, Line, number_columns

TITLES = {"재무상태표": "BS", "대차대조표": "BS", "포괄손익계산서": "CIS", "손익계산서": "IS", "현금흐름표": "CF",
          "자본변동표": "SCE", "이익잉여금처분계산서": "RE", "결손금처리계산서": "RE", "이익잉여금처분계산서(안)": "RE"}
UNITS = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}
# a title line, spaces removed: "연결재무상태표", "1.별도재무상태표" (영업보고서 number their statements)
_TITLE = re.compile(r"^(?:\d{1,2}\.|[ⅠⅡⅢⅣⅤ]+\.)?(연결|별도)?(" + "|".join(sorted(TITLES, key=len, reverse=True)) + r")$")
_UNIT = re.compile(r"단위\s*[:：]?\s*(백만원|천원|억원|원)")
_ORDINAL = re.compile(r"제\s*(\d+)\s*(?:\(\s*(당|전|전전)\s*\))?\s*기")
_PERIOD_LINE = re.compile(r"제\s*(\d+)\s*(?:\([^)]*\))?\s*기.*?(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*(?:현재|까지)")
_DATED = re.compile(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일\s*(?:부터|현재|까지)")
_YEAR = re.compile(r"(\d{4})\s*(?:년|\.)")
# an item index before a label; OCR reads a Roman numeral "Ⅰ." as "|." or "I." too
_INDEX = re.compile(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*\.?|[|IVXlivx]{1,4}\s*\.|\d{1,2}[.)]|\(\d{1,2}\)|[가-하]\.|[①-⑳])\s*")
_NOTE = re.compile(r"\s*\(\s*주\s*석?\s*[\d,\s]+\)\s*$|\s+주\s*석?\s*[\d,\s]+$")  # "현금 (주4,5)", "(주석 38)"
# where the statements end: the notes section starts with a line that is only its name
_END = re.compile(r"^(?:\(?연결\)?)?(?:재무제표에대한)?주석$")
SCE_SKIPPED = ("자본변동표는 행과 열이 모두 항목인 표라 이 도구가 아직 읽지 않는다 (v0.2 범위 밖, 원본을 직접 확인)")


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
    sums_checked: int | None = None  # balance identities and subtotals checked (per period column), when run


def parse_amount(printed: str, unit: int | None) -> int | None:
    """The value in 원 of an amount as printed, or None for a dash. Raises ValueError when it is not an amount.

    "(1,234)", "△1,234", "-1,234" are negative. Separators are removed here; whether they were plausible is
    judged in verify.py, so a misread "300,870.903" is not silently accepted there.
    """
    text = printed.replace(" ", "").replace("（", "(").replace("）", ")").replace("−", "-")
    own = UNIT_SUFFIX.search(text)
    if own:  # "(2,447)원": the amount states its unit
        text, unit = text[:own.start()], UNITS[own.group(1)]
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
    label = re.sub(r"(?<=[가-힣)])\s+\d{1,2}(\s*,\s*\d{1,2})*$", "", label)  # a note number joined to the label
    if ocr:  # stray marks OCR puts before a label ("| 유동자산", "© 비유동자산"), an item number without its dot
        label = _INDEX.sub("", re.sub(r"^[^\w가-힣(]+", "", label)).strip()
        label = re.sub(r"^\d{1,2}\s+(?=[가-힣])", "", label)  # "5 미수금" (the model dropped "5."'s dot)
    if ocr:  # OCR splits Hangul syllables of one word ("자 산 총계"); statement labels rarely need those spaces
        label = re.sub(r"(?<=[가-힣]) (?=[가-힣(])|(?<=[가-힣(]) (?=[가-힣)])", "", label)
    return label


def row_unit(label: str) -> tuple[str, int | None]:
    """A row that states its own unit ("기본주당이익(단위 : 원)"): the label without it, and that unit."""
    found = _UNIT.search(label.replace(" ", ""))
    if not found:
        # per-share amounts are in 원 whatever the table's unit (K-IFRS statements print them so); a 주당이익 row
        # under a 백만원 table without its own unit mark was once read a million times too large
        return label, (1 if re.search(r"주당\s*(순)?\s*(이익|손실|손익)", label) else None)
    return clean_label(re.sub(r"\(?\s*단\s*위\s*[:：]?\s*[천백만억]*\s*원\s*\)?", "", label)), UNITS[found.group(1)]


def account_of(label: str) -> str | None:
    """The tool's account for a label, by the names it already uses (accounts.py); other labels have none."""
    key = normalize_name(label)
    for account in ACCOUNTS.values():
        if key in {normalize_name(name) for name in account.names}:
            return account.key
    return None


def title_parts(compact: str) -> tuple[str, bool, str]:
    """(kind, consolidated, title without its item number) of a title line with spaces removed."""
    match = _TITLE.match(compact)
    return TITLES[match.group(2)], match.group(1) == "연결", (match.group(1) or "") + match.group(2)


def is_title(line: Line) -> bool:
    return bool(_TITLE.match(re.sub(r"\s+", "", line.text)))


def is_statement_start(lines: Sequence[Line], index: int, in_notes: bool = False) -> bool:
    """A title line that starts a statement: a period line or the unit line follows within a few lines on its
    page. Inside the notes, where tables have unit lines too, only a dated period line counts: a notes heading
    "37. 현금흐름표" was once read as a 141-row statement."""
    line = lines[index]
    if not is_title(line):
        return False
    following = [other.text for other in lines[index + 1:index + 6] if other.page == line.page]
    if any(_DATED.search(text) for text in following):
        return True
    return not in_notes and any(_UNIT.search(text.replace(" ", "")) for text in following)


def is_notes_start(line: Line, earlier_on_page: Sequence[Line]) -> bool:
    """The notes heading ("주석", "연결재무제표에 대한 주석"): a line that is only that, above any amount on its
    page. A "주석" column heading shares its line with the period headings, so it does not match."""
    return bool(_END.match(re.sub(r"\s+", "", line.text))) and not any(
        cell.is_amount for other in earlier_on_page for cell in other.cells)


def unit_of(body: Sequence[Line], before: Sequence[Line] = ()) -> str | None:
    """The statement's unit line: below the title and above the first amount, else just above the title on its
    page. A row label carrying its own unit ("기본주당이익(단위 : 원)") is never the statement's unit: on a real
    report that row, on the page before a statement, once made every amount of the statement a million times
    too small."""
    def found(lines):
        for line in lines:
            if any(cell.is_amount for cell in line.cells):
                return None
            match = _UNIT.search(line.text.replace(" ", ""))
            if match:
                return match.group(1)
        return None
    return found(body) or found(list(before)[::-1])


_PAGE_NUMBER = re.compile(r"[-–]?\s*\d{1,3}\s*[-–]?|\d{1,3}\s*/\s*\d{1,3}")


def without_page_furniture(lines: Sequence[Line]) -> list[Line]:
    """Lines without each page's running header or footer when it carries a page number ("Part 3. 재무제표  35"):
    the number read as an amount once made a row of its own."""
    furniture = set()
    for page in {line.page for line in lines}:
        on_page = [line for line in lines if line.page == page]
        if len(on_page) < 3:
            continue
        height = median_cell_height(on_page[len(on_page) // 2])
        for line, gap in ((on_page[0], on_page[1].top - on_page[0].bottom),
                          (on_page[-1], on_page[-1].top - on_page[-2].bottom)):
            numbers = [cell for cell in line.cells if re.search(r"\d", cell.text) and not re.search(r"[가-힣A-Za-z]", cell.text)]
            if (len(numbers) == 1 and len(line.cells) <= 3 and gap > 2 * height
                    and _PAGE_NUMBER.fullmatch(numbers[0].text.strip())):
                furniture.add(id(line))
    return [line for line in lines if id(line) not in furniture]


def find_statements(lines: Sequence[Line]) -> list[Statement]:
    """Each statement title starts a block that ends at the next title or at the notes heading; the block's rows
    are read in turn. A 자본변동표 is listed with a problem and no rows (its table is a matrix)."""
    lines = without_page_furniture(lines)
    boundaries = []  # (index, is a title)
    in_notes = False
    for index, line in enumerate(lines):
        if is_statement_start(lines, index, in_notes):
            boundaries.append((index, True))
            in_notes = False
        else:
            earlier = [other for other in lines[max(0, index - 80):index] if other.page == line.page]
            if is_notes_start(line, earlier):
                boundaries.append((index, False))
                in_notes = True
    statements = []
    for position, (start, title) in enumerate(boundaries):
        if not title:
            continue
        end = boundaries[position + 1][0] if position + 1 < len(boundaries) else len(lines)
        statement = read_statement(lines[start], lines[start + 1:end], lines[max(0, start - 3):end])
        statements.append(statement)
    return statements


def read_statement(title_line: Line, body: Sequence[Line], context: Sequence[Line]) -> Statement:
    compact = re.sub(r"\s+", "", title_line.text)
    kind, consolidated, title = title_parts(compact)
    unit_text = unit_of(body, before=[line for line in context if line.page == title_line.page and line.top < title_line.top])
    unit = UNITS.get(unit_text) if unit_text else None
    problems = [] if unit else ["단위 줄을 찾지 못해 금액 단위를 알 수 없다"]
    if kind == "SCE":
        return Statement(kind, consolidated, title, title_line.page, unit, unit_text, [], [],
                         problems + [SCE_SKIPPED])
    height = sorted(cell.bottom - cell.top for line in body for cell in line.cells)
    tolerance = 2.0 * (height[len(height) // 2] if height else 10.0)
    columns = number_columns(body, tolerance)
    periods = _period_columns(body, columns, tolerance, context)
    columns, periods = _merge_nested(body, columns, periods, context)
    # where the amounts start: the left edge of the leftmost amount in a period column (notes are left of it)
    placed_left = [cell.x0 for line in body for cell in line.cells if cell.is_amount and not _is_dash(cell.text)
                   and _period_index(cell, columns, periods, tolerance) is not None]
    amounts_left = min(placed_left) if placed_left else float("inf")
    rows = []
    orphans: list[str] = []  # amounts that end up in no row: a broken table, never silently dropped

    def unplaced_of(cells, label=""):
        return [f"{cell.page}쪽 '{cell.text}'" + (f" ({label})" if label else "") for cell in cells
                if not _is_note_like(cell, columns, periods, tolerance, amounts_left)]

    for line in body:
        amounts = {}
        label_cells = []
        for cell in line.cells:
            index = next((i for i, column in enumerate(columns) if column.holds(cell, tolerance)), None)
            if index is not None and columns[index].header == NOTE_COLUMN and not re.search(r"[가-힣]", cell.text):
                continue  # note references, neither label nor amount (a long label may reach into the column)
            if index is not None and re.search(r"[가-힣]", cell.text) and not cell.is_amount:
                index = None  # words are a label wherever they end
            if index is not None and columns[index].header.isdigit():  # merged under a period heading
                index = int(columns[index].header)
            if cell.is_amount and index is not None and index < len(periods) and not _is_note_column(periods[index]):
                if index in amounts:
                    continue  # two amounts of one line in one period: left unplaced, the row is marked below
                try:
                    amounts[index] = Amount(cell, parse_amount(cell.text, unit), cell.text, index)
                except ValueError:
                    label_cells.append(cell)
            elif index is None:
                label_cells.append(cell)
        line_amounts = [cell for cell in line.cells if cell.is_amount and not _is_dash(cell.text)]
        wrapped = False
        if amounts and not label_cells:
            label_cells, wrapped = _wrapped_label(body, line), True
        if not amounts or not label_cells:
            words = [cell.text for cell in line.cells if not cell.is_amount and re.search(r"[가-힣A-Za-z]", cell.text)]
            orphans += unplaced_of(line_amounts, clean_label(" ".join(words)) if words else "")
            continue
        label_cells = without_section_column(label_cells)
        label_cell = label_cells[0]
        # a label printed with wide letter spacing ("자    본    총    계") comes as several cells
        texts = [cell.text for cell in label_cells if not cell.is_amount] or [label_cell.text]
        # a label wrapped around its amounts breaks inside a word ("…금융자산의 감" / "소"): joined as written
        label = clean_label(("" if wrapped else " ").join(texts), ocr=label_cell.method == "ocr")
        label, own_unit = row_unit(label)
        if own_unit:  # "기본주당이익(단위 : 원)": this row's amounts are in its own unit
            for index, amount in list(amounts.items()):
                amounts[index] = Amount(amount.cell, parse_amount(amount.printed, own_unit), amount.printed, index)
        if not re.search(r"[가-힣A-Za-z]", label):  # no label, or only a mark like "-"
            orphans += unplaced_of(line_amounts)
            continue
        unplaced = unplaced_of([cell for cell in line_amounts if all(cell is not item.cell for item in amounts.values())],
                               label)
        orphans += unplaced
        rows.append(Row(label, account_of(label), label_cell, amounts, len(unplaced)))
    if kind == "BS" and not {"자산총계", "부채총계", "자본총계"} <= {re.sub(r"\s+", "", row.label) for row in rows}:
        problems.append("자산총계·부채총계·자본총계 줄을 모두 찾지 못해 합계 검산을 하지 못했다")
    empty = [row.label for row in rows for index, period in enumerate(periods)
             if index not in row.amounts and not _is_note_column(period)]
    if empty:
        problems.append(f"빈 칸 {len(empty)}개 ({', '.join(dict.fromkeys(empty))}): 원본이 '-'(해당 없음)인지, "
                        "읽지 못한 숫자인지 확인 필요")
    if orphans:
        shown = ", ".join(orphans[:12]) + (f" 외 {len(orphans) - 12}개" if len(orphans) > 12 else "")
        problems.append(f"표에 넣지 못한 금액 {len(orphans)}개 ({shown}): 줄이나 열을 복원하지 못한 행이 있을 수 있다 "
                        "(원본과 대조 필요)")
    return Statement(kind, consolidated, title, title_line.page, unit, unit_text, periods, rows, problems)


def without_section_column(cells: Sequence[Cell]) -> list[Cell]:
    """A row's label cells without a section word printed in its own column at the far left ("자산", "부채",
    "자본" beside the first row of each part, in a 영업보고서): the next cell starts with an item marker. Taking
    that word as the label once named the rows "자산" and "부채"."""
    cells = list(cells)
    if (len(cells) >= 2 and re.fullmatch(r"[가-힣]{1,4}", cells[0].text.replace(" ", ""))
            and _INDEX.match(cells[1].text)):
        return cells[1:]
    return cells


def _period_index(cell: Cell, columns: list[Column], periods: list[PeriodColumn], tolerance: float) -> int | None:
    """The period of an amount cell by its column, or None (no column, or the note column)."""
    index = next((i for i, column in enumerate(columns) if column.holds(cell, tolerance)), None)
    if index is None or columns[index].header == NOTE_COLUMN:
        return None
    if columns[index].header.isdigit():
        return int(columns[index].header)
    return index if index < len(periods) and not _is_note_column(periods[index]) else None


def _wrapped_label(body: Sequence[Line], line: Line) -> list[Cell]:
    """A long label wrapped over two lines with the amounts printed between them ("…금융자산의 감" / amounts /
    "소"): the label-only lines touching the amount line above and below."""
    index = next(i for i, other in enumerate(body) if other is line)
    height = median_cell_height(line)
    cells = []
    for neighbour, gap in ((body[index - 1] if index else None, lambda n: line.top - n.bottom),
                           (body[index + 1] if index + 1 < len(body) else None, lambda n: n.top - line.bottom)):
        if (neighbour is not None and neighbour.page == line.page and gap(neighbour) <= 0.5 * height
                and not any(cell.is_amount for cell in neighbour.cells) and re.search(r"[가-힣]", neighbour.text)):
            cells += neighbour.cells
    return cells


def median_cell_height(line: Line) -> float:
    heights = sorted(cell.bottom - cell.top for cell in line.cells)
    return heights[len(heights) // 2] if heights else 10.0


def _is_dash(text: str) -> bool:
    return text.strip() in ("-", "–", "—")


def _is_note_like(cell: Cell, columns: list[Column], periods: list[PeriodColumn], tolerance: float,
                  amounts_left: float = float("inf")) -> bool:
    """A note reference ("8", "4, 29") rather than an amount that fits no column. It is one when it is in the note
    column, or when it is short and printed left of every amount (between the label and the amounts, where
    notes are). A short number right of that ("47", a per-share amount a little off its column) is an amount:
    treating every one- or two-digit number as a note once dropped such a row without a word."""
    index = next((i for i, column in enumerate(columns) if column.holds(cell, tolerance)), None)
    if index is not None and columns[index].header == NOTE_COLUMN:
        return True
    if index is not None and columns[index].header.isdigit():
        return False
    if index is not None and index < len(periods) and _is_note_column(periods[index]):
        return True
    short = re.fullmatch(r"\d{1,2}(\s*,\s*\d{1,2})*", cell.text.strip()) or len(re.sub(r"\D", "", cell.text)) <= 2
    return bool(short) and cell.x1 <= amounts_left


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
    merged: list[Column] = []
    for column, period in zip(columns, periods):
        if _is_note_column(period) or column.right < headings[0].x0:
            # left of the first period heading: the note column, whatever its header reads like
            merged.append(Column(column.right, header=NOTE_COLUMN))
            continue
        # a column belongs to the last heading that starts left of its right edge: headings are printed centred
        # or left-aligned over their period's positions (both seen on real reports)
        index = sum(column.right >= cell.x0 for cell in headings) - 1
        merged.append(Column(column.right, header=str(index)))
    new_periods = []
    for cell in headings:
        found = _ORDINAL.search(cell.text)
        number = int(found.group(1)) if found else None
        year, end = ends.get(number, (None, None)) if number else (None, None)
        new_periods.append(PeriodColumn(cell.text, number, year, end))
    return merged, new_periods


NOTE_COLUMN = "주석"


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
