"""AI-first reading of statement pages: a vision model reads, independent evidence confirms.

For every page:
1. The page is rendered and levelled. Evidence words come from the PDF's text layer when the page has one,
   otherwise from Tesseract on the same levelled image.
2. A photo of two pages side by side is split where no evidence word crosses (the widest gap near the middle).
3. Title, unit, period lines, and the column headers are found in the evidence; a part without them
   continues the previous part's statement.
4. The table body is cut into bands between evidence lines (about eight lines, one line of overlap), and the
   vision model transcribes each band as "label | amount | ...".
5. Each amount the model gives is looked for in the evidence line that matches its row (label and digits).
   Found there: the value is confirmed, and its period is the column header above the evidence word, not the
   model's order (statements nest detail and subtotal columns under one period). Found only elsewhere, or
   not at all: 확인 필요. The model's digits are never corrected from the evidence.
6. Amounts in the evidence that no model line claimed are reported, so a row the model skipped is not lost
   silently; the balance-sheet identities are checked as in verify.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
import re
from statistics import median
from typing import Iterator, Sequence

from .statement import (
    _END, _ORDINAL, _PERIOD_LINE, _TITLE, SCE_SKIPPED, TITLES, UNITS, Amount, PeriodColumn, Row, Statement,
    account_of, clean_label, is_notes_start, parse_amount, row_unit, unit_of,
)
from .table import Cell, Line, group_lines
from .verify import CHECKED, REVIEW, CellCheck, _balance, _subtotals, separator_problem
from .vision import SMALL_OR_GROUPED, BAND_PROMPT, META_PROMPT, BandLine, VisionError, VisionModel, parse_band, parse_meta, png_bytes
from .words import Word, image_words, skew_angle, vision_words

RENDER_SCALE = 2.0  # pixels per PDF point for the model and for OCR (144 dpi)
BAND_LINES, BAND_OVERLAP = 8, 1
LABEL_AGREEMENT = 0.75  # below this, the model's label and the evidence line's label are taken as different rows


@dataclass
class Part:
    """One statement page (or one of two pages photographed side by side)."""

    page: int
    image: object  # the levelled page image (PIL)
    words: list[Word]  # evidence words inside this part, positions in image pixels (lines for structure)
    source: str  # "PDF 글자" or "OCR"
    x_range: tuple[float, float]
    tokens: list[Word] = field(default_factory=list)  # every evidence word, also OCR's sparse-text pass


@dataclass
class Header:
    centers: list[float]  # x centre of each period header, left to right
    columns: list[PeriodColumn]
    bottom: float

    def period_of(self, x: float) -> int | None:
        if not self.centers:
            return None
        bounds = [(a + b) / 2 for a, b in zip(self.centers, self.centers[1:])]
        return sum(x > bound for bound in bounds)


@dataclass
class Reading:
    statements: list[Statement]
    checks: list[CellCheck]
    problems: list[str] = field(default_factory=list)
    calls: int = 0


def _pixels(word: Word, scale: float) -> Word:
    return Word(word.text, word.page, word.x0 * scale, word.x1 * scale, word.top * scale, word.bottom * scale,
                word.method, word.confidence, word.line_key)


def page_parts(path: Path, pages: Sequence[int] | None = None) -> Iterator[Part]:
    """The page parts one page at a time (a 150-page report is not held in memory as images)."""
    import pypdfium2
    from PIL import Image
    from .words import text_layer_words
    text_words = text_layer_words(path)
    document = pypdfium2.PdfDocument(str(path))
    try:
        for index in range(len(document)):
            number = index + 1
            if pages and number not in pages:
                continue
            image = document[index].render(scale=RENDER_SCALE).to_pil().convert("L")
            layer = [word for word in text_words if word.page == number]
            if layer:
                words, source = [_pixels(word, RENDER_SCALE) for word in layer], "PDF 글자"
            else:
                angle = skew_angle(image)
                if angle:
                    image = image.rotate(angle, fillcolor=255, resample=Image.BICUBIC)
                words, source = image_words(image, number, scale=1.0, level=False), "OCR"
            # a photo's numbers are often found only by OCR's sparse-text pass (psm 11): kept as extra evidence
            tokens = words if layer else words + image_words(image, number, scale=1.0, level=False, psm=11)
            for x_range in _split(tokens, image.width, image.height):
                inside = [word for word in words if x_range[0] <= (word.x0 + word.x1) / 2 < x_range[1]]
                found = [word for word in tokens if x_range[0] <= (word.x0 + word.x1) / 2 < x_range[1]]
                if not layer:
                    # a second OCR engine (macOS Vision, when available) as more evidence; read per part, because
                    # on a photo of two pages it reads each half far better than the whole (69 of 92 amounts vs 54)
                    crop = image.crop((int(x_range[0]), 0, int(x_range[1]), image.height))
                    found += [_shifted(word, x_range[0]) for word in vision_words(crop, number)]
                yield Part(number, image, inside, source, x_range, found)
    finally:
        document.close()


def _shifted(word: Word, dx: float) -> Word:
    return Word(word.text, word.page, word.x0 + dx, word.x1 + dx, word.top, word.bottom, word.method, word.confidence,
                word.line_key)


def _split(words: Sequence[Word], width: float, height: float) -> list[tuple[float, float]]:
    """Two parts when a landscape image has a vertical gap near the middle that no word crosses."""
    if width < 1.15 * height or not words:
        return [(0.0, float(width))]
    free_from, best = None, (0.0, 0.0)
    for x in range(int(0.35 * width), int(0.65 * width)):
        crossed = any(word.x0 < x < word.x1 for word in words)
        if not crossed and free_from is None:
            free_from = x
        if (crossed or x == int(0.65 * width) - 1) and free_from is not None:
            if x - free_from > best[1] - best[0]:
                best = (free_from, x)
            free_from = None
    if best[1] - best[0] < 0.01 * width:
        return [(0.0, float(width))]
    middle = (best[0] + best[1]) / 2
    return [(0.0, middle), (middle, float(width))]


def _header(lines: Sequence[Line], ends: dict[int, tuple[int, str]]) -> Header | None:
    """The line with two or more period headings ("제 57 (당) 기", "당기"), with each heading's x centre."""
    for line in lines:
        found = []
        for cell in line.cells:
            text = cell.text
            ordinal = _ORDINAL.search(text.replace(" ", "")) or _ORDINAL.search(text)
            if ordinal or re.search(r"(당|전)\s*기", text):
                found.append((cell, ordinal))
        if len(found) >= 2:
            columns = []
            for cell, ordinal in found:
                number = int(ordinal.group(1)) if ordinal else None
                year, end = ends.get(number, (None, None)) if number else (None, None)
                columns.append(PeriodColumn(cell.text, number, year, end))
            return Header([(cell.x0 + cell.x1) / 2 for cell, _ in found], columns, max(cell.bottom for cell, _ in found))
    return None


def _different_accounts(first: str, second: str) -> bool:
    """Whether two labels name different accounts: dissimilar, or one inside the other ("유동자산" in "비유동자산"),
    which a similarity score alone would call the same."""
    a, b = _key(first), _key(second)
    if a == b:
        return False
    if a in b or b in a:
        return True
    return SequenceMatcher(None, a, b).ratio() < LABEL_AGREEMENT


def _key(text: str) -> str:
    return re.sub(r"[^가-힣A-Za-z]", "", clean_label(text, ocr=True))


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _is_amount_word(text: str) -> bool:
    """An amount as printed: digits grouped by three, or a small amount in parentheses or of three digits
    ("(973)", "682"). Note numbers ("4", "29", "4, 29") are not amounts."""
    return bool(SMALL_OR_GROUPED.fullmatch(text.replace(" ", "")))


def _existing_row(statement: Statement, label: str, line: Line | None) -> int | None:
    """The row this reading continues: the one read from the same printed line (the overlap of two bands).
    Without an evidence line, a row of the same label among the last few rows. A label may appear twice in
    a statement (관계기업 지분 under both parts of 기타포괄손익); matching on the label alone once merged
    the second row into the first and dropped its amounts."""
    if line is not None:
        return next((index for index, row in enumerate(statement.rows)
                     if row.label_cell is not None and any(row.label_cell is cell for cell in line.cells)), None)
    recent = range(max(0, len(statement.rows) - BAND_OVERLAP - 1), len(statement.rows))
    return next((index for index in recent if _key(statement.rows[index].label) == _key(label)), None)


def _bands(lines: Sequence[Line]) -> list[tuple[float, float, list[Line]]]:
    if not lines:
        return []
    bands = []
    start = 0
    while start < len(lines):
        chunk = list(lines[start:start + BAND_LINES])
        top = (chunk[0].top + (lines[start - 1].cells[0].bottom if start else chunk[0].top - 12)) / 2
        nxt = start + len(chunk)
        last_bottom = max(cell.bottom for cell in chunk[-1].cells)
        bottom = (last_bottom + lines[nxt].top) / 2 if nxt < len(lines) else last_bottom + 12
        bands.append((max(0.0, top - 4), bottom + 4, chunk))
        if nxt >= len(lines):
            break
        start = nxt - BAND_OVERLAP
    return bands


def _match_line(item: BandLine, lines: Sequence[Line]) -> Line | None:
    """The evidence line of a model line: shared amount digits first, then label similarity."""
    want = {_digits(amount) for amount in item.amounts if _digits(amount)}
    best, best_score = None, 0.0
    for line in lines:
        have = {_digits(cell.text) for cell in line.cells if _is_amount_word(cell.text)}
        label = next((cell.text for cell in line.cells if re.search(r"[가-힣]", cell.text)), "")
        similarity = SequenceMatcher(None, _key(item.label), _key(label)).ratio() if label else 0.0
        score = 2 * len(want & have) + similarity
        if score > best_score and (similarity >= 0.5 or want & have):
            best, best_score = line, score
    return best


def read_document(path: Path, model: VisionModel, pages: Sequence[int] | None = None) -> Reading:
    """Statements read by ``model`` and checked against the page's evidence (see the module docstring)."""
    state = _State()
    for part in page_parts(path, pages):
        lines = group_lines(part.words)
        title_line = next((line for line in lines if _TITLE.match(re.sub(r"\s+", "", line.text))), None)
        if title_line is not None or part.source == "PDF 글자":
            _read_with_page_structure(part, lines, title_line, model, state)
        else:
            _read_with_model_structure(part, model, state)
    for s_index, statement in enumerate(state.statements):
        own = [check for check in state.checks if check.statement == s_index]
        if s_index in state.unverified_units:
            for check in own:
                check.flag(f"단위를 원본에서 확인하지 못했다 (AI가 읽은 단위: {statement.unit_text})")
        if statement.kind == "SCE":
            continue
        by_cell = {(check.row, check.column): check for check in own}
        if statement.kind == "BS" and not _balance(statement, by_cell):
            statement.problems.append("합계 줄을 찾지 못해 재무상태표 검산을 하지 못했다")
        if not _subtotals(statement, by_cell):
            statement.problems.append("소계와 항목의 위치를 구분하지 못해 소계 검산을 하지 못했다")
    return Reading(state.statements, state.checks, state.problems, state.calls)


@dataclass
class _State:
    statements: list[Statement] = field(default_factory=list)
    checks: list[CellCheck] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    calls: int = 0
    header: Header | None = None
    ends: dict[int, tuple[int, str]] = field(default_factory=dict)
    unverified_units: set[int] = field(default_factory=set)
    closed: bool = False  # the notes section started: pages until the next title belong to no statement

    @property
    def current(self) -> Statement | None:
        return self.statements[-1] if self.statements and not self.closed else None

    def ask(self, model: VisionModel, image, prompt: str, split: bool = False) -> str | None:
        """The model's answer, or None (reported). ``split``: a band that ran out of output budget is asked again
        as its upper and lower halves (with a little overlap), once; seen on one band of a real photo."""
        self.calls += 1
        try:
            return model.transcribe(png_bytes(image), prompt)
        except VisionError as exc:
            if split and "budget" in str(exc) and image.height >= 80:
                middle, overlap = image.height // 2, image.height // 10
                halves = [image.crop((0, 0, image.width, middle + overlap)),
                          image.crop((0, middle - overlap, image.width, image.height))]
                answers = [self.ask(model, half, prompt) for half in halves]
                if all(answer is not None for answer in answers):
                    return "\n".join(answers)
                return "\n".join(answer for answer in answers if answer) or None
            target = self.current.problems if self.current else self.problems
            target.append(f"AI가 한 부분을 읽지 못했다: {exc}")
            return None


def _new_statement(state: _State, title: str, page: int, unit_text: str | None) -> Statement:
    compact = re.sub(r"\s+", "", title)
    kind = TITLES[_TITLE.match(compact).group(2)]
    statement = Statement(kind, compact.startswith("연결"), compact, page, UNITS.get(unit_text) if unit_text else None,
                          unit_text, [], [], [] if unit_text else ["단위 줄을 찾지 못해 금액 단위를 알 수 없다"])
    if kind == "SCE":
        statement.problems.append(SCE_SKIPPED)
    state.statements.append(statement)
    state.header, state.closed = None, False
    return statement


def _read_with_page_structure(part: Part, lines: Sequence[Line], title_line: Line | None, model: VisionModel,
                              state: _State) -> None:
    """The page's own lines give the title, unit, headers, and band edges (text layer, or a readable scan)."""
    text = " ".join(line.text for line in lines)
    for found in _PERIOD_LINE.finditer(text):
        ordinal, year, month, day = (int(value) for value in found.groups())
        state.ends[ordinal] = (year, f"{year:04d}-{month:02d}-{day:02d}")
    if title_line is not None:
        unit_text = unit_of([line for line in lines if line.top > title_line.top],
                            before=[line for line in lines if line.top < title_line.top])
        _new_statement(state, title_line.text, part.page, unit_text)
    notes = next((line for index, line in enumerate(lines)
                  if is_notes_start(line, lines[:index]) and (title_line is None or line.top > title_line.top)), None)
    statement = state.current
    if statement is None or statement.kind == "SCE":
        state.closed = state.closed or notes is not None
        return  # pages before the first statement (cover, auditor's report), the notes, or a 자본변동표
    if notes is not None:
        lines = [line for line in lines if line.top < notes.top]
    part_header = _header(lines, state.ends)
    if part_header is not None:
        state.header = part_header
        if not statement.columns:
            statement.columns = part_header.columns
    if state.header is None:
        statement.problems.append(f"{part.page}쪽: 열 머리글(당기·전기)을 찾지 못해 이 쪽의 금액은 기간을 정하지 못했다")
    top = part_header.bottom if part_header else (title_line.cells[0].bottom if title_line else 0.0)
    body = [line for line in lines if line.top > top and any(_is_amount_word(cell.text) for cell in line.cells)]
    claimed: set[int] = set()
    s_index = len(state.statements) - 1
    for band_top, band_bottom, band_lines in _bands(body):
        crop = part.image.crop((int(part.x_range[0]), int(band_top), int(part.x_range[1]), int(band_bottom)))
        answer = state.ask(model, crop, BAND_PROMPT, split=True)
        for item in parse_band(answer or ""):
            _add_row(statement, state.checks, s_index, item, band_lines, state.header, part, claimed)
    for line in body:
        for cell in line.cells:
            if _is_amount_word(cell.text) and id(cell) not in claimed:
                statement.problems.append(f"{part.page}쪽: 원본의 금액 '{cell.text}'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)")
    if notes is not None:
        state.closed = True


def _read_with_model_structure(part: Part, model: VisionModel, state: _State) -> None:
    """A photo or poor scan whose OCR gives no usable lines: the model reads the title, unit, and headers too,
    and the table in overlapping bands; OCR words found anywhere in the band are the evidence."""
    height = part.image.height
    top_crop = part.image.crop((int(part.x_range[0]), 0, int(part.x_range[1]), int(height * 0.35)))
    meta = parse_meta(state.ask(model, top_crop, META_PROMPT) or "")
    ocr_text = re.sub(r"\s+", "", " ".join(word.text for word in part.tokens))
    digit_heights = [word.height for word in part.tokens if _is_amount_word(word.text)]
    if digit_heights and median(digit_heights) / RENDER_SCALE < 12:
        state.problems.append(f"{part.page}쪽: 글자 높이가 약 {median(digit_heights) / RENDER_SCALE:.0f}픽셀로 작아 OCR 증거가 약하다 "
                              "(한 쪽씩 가까이 찍거나 스캔 해상도를 높이면 확인되는 칸이 늘어난다)")
    title = re.sub(r"\s+", "", meta.title)
    if _TITLE.match(title):
        unit = next((name for name in sorted(UNITS, key=len, reverse=True) if name in meta.unit.replace(" ", "")), None)
        statement = _new_statement(state, title, part.page, unit)
        if unit and unit not in ocr_text:
            state.unverified_units.add(len(state.statements) - 1)
    elif _END.match(title):
        state.closed = True
    statement = state.current
    if statement is None or statement.kind == "SCE":
        return
    for line in meta.periods:
        found = _PERIOD_LINE.search(line.replace(":", " "))
        if found:
            ordinal, year, month, day = (int(value) for value in found.groups())
            state.ends[ordinal] = (year, f"{year:04d}-{month:02d}-{day:02d}")
    headings = [column for column in meta.columns if _ORDINAL.search(column) or re.search(r"(당|전)\s*기", column)]
    if headings and not statement.columns:
        statement.columns = []
        for heading in headings:
            found = _ORDINAL.search(heading)
            number = int(found.group(1)) if found else None
            year, end = state.ends.get(number, (None, None)) if number else (None, None)
            statement.columns.append(PeriodColumn(heading, number, year, end))
    if not statement.columns:
        statement.problems.append(f"{part.page}쪽: 열 머리글(당기·전기)을 찾지 못해 금액의 기간을 정하지 못했다")
        return
    s_index = len(state.statements) - 1
    claimed: set[int] = set()
    band, step = 0.20 * height, 0.15 * height
    y = 0.0
    while y < height:
        box = (int(part.x_range[0]), int(y), int(part.x_range[1]), int(min(height, y + band)))
        answer = state.ask(model, part.image.crop(box), BAND_PROMPT, split=True)
        tokens = [word for word in part.tokens if box[1] <= (word.top + word.bottom) / 2 <= box[3]]
        for item in parse_band(answer or ""):
            _add_row_by_tokens(statement, state.checks, s_index, item, tokens, part, claimed)
        if y + band >= height:
            break
        y += step


def _add_row_by_tokens(statement: Statement, checks: list[CellCheck], s_index: int, item: BandLine,
                       tokens: Sequence[Word], part: Part, claimed: set[int]) -> None:
    """Without evidence lines: an amount is confirmed when OCR read the same digits in the same band; its period
    is the model's left-to-right order, which is checked against the number of period columns."""
    label, own_unit = row_unit(clean_label(item.label, ocr=True))
    unit = own_unit or statement.unit
    amounts = [printed for printed in item.amounts if printed not in ("-", "–", "—")]
    if not label or not amounts:
        return
    existing = _existing_row(statement, label, None)
    row = statement.rows[existing] if existing is not None else Row(label, account_of(label), None, {})
    r_index = existing if existing is not None else len(statement.rows)
    for position, printed in enumerate(amounts):
        if position >= len(statement.columns):
            break
        column = position
        try:
            value = parse_amount(printed, unit)
        except ValueError:
            continue
        if column in row.amounts:
            if row.amounts[column].value != value:  # two overlapping bands read this cell differently
                for check in checks:
                    if (check.statement, check.row, check.column) == (s_index, r_index, column):
                        check.flag(f"겹친 두 띠에서 다른 숫자로 읽었다 ({row.amounts[column].printed}, {printed})")
            continue
        token = next((word for word in tokens if _digits(word.text) == _digits(printed) and id(word) not in claimed), None)
        check = CellCheck(s_index, r_index, column, evidence="OCR" if token else "")
        if token is not None:
            claimed.add(id(token))
        else:
            check.flag("원본 OCR에서 같은 숫자를 찾지 못했다 (AI만 읽은 숫자)")
        if len(amounts) != len(statement.columns):
            check.flag(f"이 줄에서 금액 {len(amounts)}개를 읽었는데 기간 열은 {len(statement.columns)}개라 기간 배정이 불확실하다")
        problem = separator_problem(printed)
        if problem:
            check.flag(problem)
        anchor = Cell([token]) if token else Cell([Word(printed, part.page, part.x_range[0], part.x_range[1], 0, 0, "ai")])
        row.amounts[column] = Amount(anchor, value, printed, column)
        checks.append(check)
    if existing is None and row.amounts:
        statement.rows.append(row)


def _add_row(statement: Statement, checks: list[CellCheck], s_index: int, item: BandLine, band_lines: Sequence[Line],
             header: Header | None, part: Part, claimed: set[int]) -> None:
    label = clean_label(item.label, ocr=True)
    if not label:
        return
    evidence_line = _match_line(item, band_lines)
    label_problem = None
    if evidence_line is not None:
        source_label = clean_label(next((c.text for c in evidence_line.cells if re.search(r"[가-힣]", c.text)), ""), ocr=True)
        if part.source == "PDF 글자" and source_label:
            # the text layer is exact: the row takes the page's own label, as its amounts take the page's digits
            # and their period the page's column position, so the output is right even when the model's label
            # was not; that the model confused rows is reported for the document, not for the cell
            if _key(label) != _key(source_label):
                statement.problems.append(f"{part.page}쪽: AI가 '{source_label}' 줄을 '{label}'(으)로 읽어 원본 계정명을 썼다")
            label = source_label
        elif source_label and _different_accounts(label, source_label):
            label_problem = (f"AI가 읽은 계정명 '{label}'과 숫자를 찾은 원본 줄의 계정명 '{source_label}'이 다르다 "
                             "(숫자를 다른 줄에 붙였을 수 있다)")
    label, own_unit = row_unit(label)
    if own_unit is None:
        _, own_unit = row_unit(item.label)
    unit = own_unit or statement.unit
    existing = _existing_row(statement, label, evidence_line)
    row = statement.rows[existing] if existing is not None else Row(
        label, account_of(label), evidence_line.cells[0] if evidence_line is not None else None, {})
    for position, printed in enumerate(item.amounts):
        if printed in ("-", "–", "—"):
            continue
        digits = _digits(printed)
        cell = None
        if evidence_line is not None:
            cell = next((c for c in evidence_line.cells if _is_amount_word(c.text) and _digits(c.text) == digits
                         and id(c) not in claimed), None)
        reasons = [label_problem] if label_problem else []
        if cell is not None:
            claimed.add(id(cell))
            column = header.period_of((cell.x0 + cell.x1) / 2) if header else None
            if column is None:
                column = position
                reasons.append("열 머리글이 없어 기간을 AI가 읽은 순서로 정했다")
        else:
            elsewhere = next((c for line in band_lines for c in line.cells if _is_amount_word(c.text)
                              and _digits(c.text) == digits and id(c) not in claimed), None)
            reasons.append("원본의 다른 줄에서만 같은 숫자를 찾았다" if elsewhere else "원본에서 같은 숫자를 찾지 못했다 (AI가 잘못 읽었을 수 있다)")
            column = position if position < max(1, len(statement.columns)) else None
            if column is None:
                continue
        if column in row.amounts:
            continue  # the overlap line between two bands, already read
        try:
            value = parse_amount(printed, unit)
        except ValueError:
            continue
        anchor = cell or Cell([Word(printed, part.page, part.x_range[0], part.x_range[1], 0, 0, "ai")])
        row.amounts[column] = Amount(anchor, value, printed, column)
        r_index = existing if existing is not None else len(statement.rows)
        check = CellCheck(s_index, r_index, column, evidence=part.source if cell is not None else "")
        for reason in reasons:
            check.flag(reason)
        problem = separator_problem(printed)
        if problem:
            check.flag(problem)
        if statement.unit is None:
            check.flag("금액 단위를 알 수 없다")
        checks.append(check)
    if existing is None and row.amounts:
        statement.rows.append(row)
