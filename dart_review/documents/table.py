"""Lines and cells from positioned words.

A financial statement in a PDF is a label column on the left and right-aligned number columns. Words are
grouped into lines by their vertical middle, then into cells by the horizontal gap between them; a cell
that looks like an amount is placed in the number column whose right edge it shares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from statistics import median
from typing import Sequence

from .words import Word

# an amount as printed: digits with or without separators, optional parentheses / minus / triangle for a negative,
# or a dash for none. Loose on purpose: verify.py judges whether the separators are plausible.
AMOUNT = re.compile(r"^[(（]?[△▲\-−]?\s?[\d][\d,.\s]*[)）]?$|^[-–—]$")


@dataclass
class Cell:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(word.text for word in self.words)

    @property
    def x0(self) -> float:
        return min(word.x0 for word in self.words)

    @property
    def x1(self) -> float:
        return max(word.x1 for word in self.words)

    @property
    def top(self) -> float:
        return min(word.top for word in self.words)

    @property
    def bottom(self) -> float:
        return max(word.bottom for word in self.words)

    @property
    def page(self) -> int:
        return self.words[0].page

    @property
    def confidence(self) -> float | None:
        scores = [word.confidence for word in self.words if word.confidence is not None]
        return min(scores) if scores else None

    @property
    def method(self) -> str:
        return "ocr" if any(word.method == "ocr" for word in self.words) else "text"

    @property
    def is_amount(self) -> bool:
        return bool(AMOUNT.match(self.text))


@dataclass
class Line:
    page: int
    cells: list[Cell] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(cell.text for cell in self.cells)

    @property
    def top(self) -> float:
        return min(cell.top for cell in self.cells)


def group_lines(words: Sequence[Word]) -> list[Line]:
    """Words on one baseline form a line; lines are ordered top to bottom, page by page."""
    lines: list[Line] = []
    for page in sorted({word.page for word in words}):
        on_page = sorted((word for word in words if word.page == page), key=lambda word: (word.middle, word.x0))
        if not on_page:
            continue
        if all(word.line_key is not None for word in on_page):
            # OCR: Tesseract already follows each text line, even a slightly tilted one
            keyed: dict[tuple[int, ...], list[Word]] = {}
            for word in on_page:
                keyed.setdefault(word.line_key, []).append(word)
            for row in sorted(keyed.values(), key=lambda items: median(item.middle for item in items)):
                lines.append(Line(page, _cells(sorted(row, key=lambda word: word.x0))))
            continue
        tolerance = 0.5 * median(word.height for word in on_page)
        rows: list[list[Word]] = []
        for word in on_page:
            if rows and abs(word.middle - median(item.middle for item in rows[-1])) <= tolerance:
                rows[-1].append(word)
            else:
                rows.append([word])
        for row in rows:
            lines.append(Line(page, _cells(sorted(row, key=lambda word: word.x0))))
    return lines


def _cells(row: list[Word]) -> list[Cell]:
    """Neighbouring words form one cell unless the gap is wider than about two characters.

    A label like "당기순이익 (손실)" stays one cell; a label and its amount, or two amounts, do not.
    Amounts never merge with each other, whatever the gap (OCR can put two columns close together).
    """
    height = median(word.height for word in row)
    cells: list[Cell] = []
    for word in row:
        if cells:
            previous = cells[-1]
            gap = word.x0 - previous.x1
            both_amounts = AMOUNT.match(previous.words[-1].text) and AMOUNT.match(word.text)
            # a number cannot end with a separator: OCR split "288,361,693" into "288," and "361,693"
            broken_number = both_amounts and previous.words[-1].text[-1:] in ",." and gap <= 1.2 * height
            if broken_number:
                previous.words[-1] = _joined(previous.words[-1], word)
                continue
            if gap <= 1.2 * height and not both_amounts:
                previous.words.append(word)
                continue
        cells.append(Cell([word]))
    return cells


def _joined(first: Word, second: Word) -> Word:
    confidences = [value for value in (first.confidence, second.confidence) if value is not None]
    return Word(first.text + second.text, first.page, first.x0, second.x1, min(first.top, second.top),
                max(first.bottom, second.bottom), first.method, min(confidences) if confidences else None, first.line_key)


@dataclass
class Column:
    right: float  # the shared right edge of the amounts in it
    header: str = ""

    def holds(self, cell: Cell, tolerance: float) -> bool:
        return abs(cell.x1 - self.right) <= tolerance


def number_columns(lines: Sequence[Line], tolerance: float) -> list[Column]:
    """Columns found from the right edges of the amount cells (amounts are right-aligned), left to right.

    A column needs amounts on at least two lines, so a stray number in a sentence is not a column.
    """
    edges = sorted(cell.x1 for line in lines for cell in line.cells if cell.is_amount)
    groups: list[list[float]] = []
    for edge in edges:
        if groups and edge - groups[-1][-1] <= tolerance:
            groups[-1].append(edge)
        else:
            groups.append([edge])
    return [Column(median(group)) for group in groups if len(group) >= 2]
