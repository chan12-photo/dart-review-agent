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
    account_of, clean_label, is_notes_start, is_statement_start, title_parts, without_section_column, without_page_furniture, parse_amount, row_unit, unit_of,
)
from .table import Cell, Line, group_lines
from .verify import CHECKED, REVIEW, CellCheck, check_sums, separator_problem
from .vision import SMALL_OR_GROUPED, BAND_PROMPT, META_PROMPT, BandLine, VisionError, VisionModel, parse_band, parse_meta, png_bytes
from .words import Word, image_words, skew_angle, vision_words

RENDER_SCALE = 2.0  # pixels per PDF point for the model and for OCR (144 dpi)
BAND_LINES, BAND_OVERLAP = 8, 1
VISION_LINE = 900  # words.vision_words marks its words with line_key (900, n, 0)
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
    starts: list[float]  # x where each period heading starts, left to right
    columns: list[PeriodColumn]
    bottom: float

    def period_of(self, right: float) -> int | None:
        """The period of an amount whose right edge is ``right``: the last heading that starts left of it.
        Headings are printed centred or left-aligned over their period's detail and subtotal positions; the
        midpoint between heading centres once put a current-year subtotal under the prior year. An amount left
        of the first heading (the note column) has no period."""
        index = sum(right >= start for start in self.starts) - 1
        return index if index >= 0 else None


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
            return Header([cell.x0 for cell, _ in found], columns, max(cell.bottom for cell, _ in found))
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
    return bool(SMALL_OR_GROUPED.fullmatch(re.sub(r"(백만|천)?원$", "", text.replace(" ", ""))))


def _label_cell(line: Line | None) -> Cell | None:
    """The cell where a printed row's label starts (its item marker and indentation give the row's depth)."""
    if line is None:
        return None
    words = without_section_column([c for c in line.cells if re.search(r"[가-힣]", c.text) and not c.is_amount])
    # a line with no label of its own (a label wrapped onto the lines around it): its depth is not known; an amount
    # cell's position taken for the label's once made a row the child of the one above, and its sum failed
    return words[0] if words else None


def _is_bare_small(text: str) -> bool:
    """A one- or two-digit number without parentheses: an amount ("42") or a note number ("8")."""
    return bool(re.fullmatch(r"[-−△]?\d{1,2}", text.replace(" ", "")))


def _is_amount_like(cell: Cell, header: Header | None, line: Line | None = None) -> bool:
    """An amount, or a small number printed under a period heading (a per-share amount "47"). A bare one- or
    two-digit number counts only in a free period slot of its line (see ``_in_free_slot``)."""
    if _is_amount_word(cell.text):
        return True
    text = re.sub(r"(백만|천)?원$", "", cell.text.replace(" ", ""))
    if header is None or header.period_of(cell.x1) is None:
        return False
    if _is_bare_small(text):
        return line is None or _in_free_slot(cell, line, header)
    return bool(re.fullmatch(r"[(（]?[-−△]?\d{1,3}[)）]?", text))


def _in_free_slot(cell: Cell, line: Line, header: Header) -> bool:
    """A bare one- or two-digit number is an amount only where its period has no other amount on the line. A note
    number printed right of an amount falls under the same period as that amount ("매출액 1,000 | 1"); a per-share
    amount "42" fills a period of its own."""
    period = header.period_of(cell.x1)
    if period is None:
        return False
    return not any(other is not cell and _is_amount_word(other.text) and header.period_of(other.x1) == period
                   for other in line.cells)


def _existing_row(statement: Statement, line: Line) -> int | None:
    """The row read from the same printed line before (the overlap of two bands). A label may appear twice in
    a statement (관계기업 지분 under both parts of 기타포괄손익); matching on the label alone once merged
    the second row into the first and dropped its amounts."""
    return next((index for index, row in enumerate(statement.rows)
                 if row.label_cell is not None and any(row.label_cell is cell for cell in line.cells)), None)


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
        lines = without_page_furniture(group_lines(part.words))
        starts = [index for index in range(len(lines)) if is_statement_start(lines, index, state.closed)]
        if starts or part.source == "PDF 글자":
            # a page may hold the end of one statement and the start of others (손익계산서 and 포괄손익계산서 on
            # one page): each title starts its own part of the page; reading only the first title once put the
            # second statement's rows under the first
            if not starts or starts[0] > 0:
                _read_with_page_structure(part, lines[:starts[0]] if starts else lines, None, model, state)
            for position, start in enumerate(starts):
                end = starts[position + 1] if position + 1 < len(starts) else len(lines)
                _read_with_page_structure(part, lines[start:end], lines[start], model, state)
        else:
            _read_with_model_structure(part, model, state)
    for s_index, statement in enumerate(state.statements):
        own = [check for check in state.checks if check.statement == s_index]
        if s_index in state.unverified_units:
            for check in own:
                check.flag(f"단위를 원본에서 확인하지 못했다 (AI가 읽은 단위: {statement.unit_text})")
        if statement.kind == "SCE":
            continue
        unverified = {check.row for check in own if "계정명 미확인" in check.evidence}
        if unverified:
            statement.problems.append(f"계정명을 원본(OCR)으로 확인하지 못한 행 {len(unverified)}개: 숫자는 OCR로 확인했지만 "
                                      "계정명은 AI가 읽은 그대로다 (원본과 대조 필요)")
        by_cell = {(check.row, check.column): check for check in own}
        check_sums(statement, by_cell)
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
    kind, consolidated, title = title_parts(compact)
    statement = Statement(kind, consolidated, title, page, UNITS.get(unit_text) if unit_text else None,
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
    body = [line for line in lines if line.top > top and any(_is_amount_like(cell, state.header) for cell in line.cells)]
    claimed: set[int] = set()
    s_index = len(state.statements) - 1
    for band_top, band_bottom, band_lines in _bands(body):
        crop = part.image.crop((int(part.x_range[0]), int(band_top), int(part.x_range[1]), int(band_bottom)))
        answer = state.ask(model, crop, BAND_PROMPT, split=True)
        for item in parse_band(answer or ""):
            _add_row(statement, state.checks, s_index, item, band_lines, state.header, part, claimed)
    for line in body:
        for cell in line.cells:
            if _is_amount_like(cell, state.header, line) and id(cell) not in claimed:
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
    claimed: dict[int, int] = {}  # id of an OCR token -> the row it confirmed
    band, step = 0.20 * height, 0.15 * height
    y = 0.0
    previous_start = len(statement.rows)  # rows of the previous band: the overlap may read them again
    while y < height:
        box = (int(part.x_range[0]), int(y), int(part.x_range[1]), int(min(height, y + band)))
        answer = state.ask(model, part.image.crop(box), BAND_PROMPT, split=True)
        tokens = [word for word in part.tokens if box[1] <= (word.top + word.bottom) / 2 <= box[3]]
        band_start = len(statement.rows)
        reread: set[int] = set()  # tokens of the previous band already matched by a re-reading in this band
        for item in parse_band(answer or ""):
            _add_row_by_tokens(statement, state.checks, s_index, item, tokens, part, claimed, previous_start, reread)
        previous_start = band_start
        if y + band >= height:
            break
        y += step
    _report_unread_tokens(statement, part, claimed)


def _add_row_by_tokens(statement: Statement, checks: list[CellCheck], s_index: int, item: BandLine,
                       tokens: Sequence[Word], part: Part, claimed: dict[int, int], recent_from: int | None = None,
                       reread: set[int] | None = None) -> None:
    """Without evidence lines (a photo): an amount is confirmed by an OCR token of the same digits on the row's
    printed line, and the row's label by the OCR words left of it on that line.

    - The amounts of one row must be on one OCR line, left to right in period order. When a digit string is
      in the band more than once and the row's other amounts do not pick the line, the cell is marked.
    - A re-reading in the overlap of two bands is known by its OCR token, which the previous band's row has
      already claimed; matching on the label or the digits once merged two different rows into one.
    - The label is compared with the OCR words on the line: a clearly different account is marked; a label
      the OCR could not read stays as the model read it and is counted as unverified on the statement.
    """
    label, own_unit = row_unit(clean_label(item.label, ocr=True))
    unit = own_unit or statement.unit
    # a one- or two-digit number cannot be told from a note number without a text layer: not taken
    amounts = [printed for printed in item.amounts if printed not in ("-", "–", "—") and not _is_bare_small(printed)]
    if not label or not amounts:
        return
    first = recent_from if recent_from is not None else len(statement.rows)
    existing = _overlap_row(amounts, tokens, claimed, first, reread if reread is not None else set())
    if existing is None:
        existing = _ai_only_repeat(statement, label, amounts, tokens, claimed, first)
    row = statement.rows[existing] if existing is not None else Row(label, account_of(label), None, {})
    r_index = existing if existing is not None else len(statement.rows)
    chosen, unsure = _row_tokens(amounts, tokens, claimed, owner=existing)
    label_reason, label_known = None, False
    line_words = _line_words(chosen, part.tokens)
    if line_words is not None:
        ocr_label = clean_label(" ".join(word.text for word in line_words), ocr=True)
        if len(re.findall(r"[가-힣]", ocr_label)) >= 2:
            if _different_accounts(label, ocr_label):  # one inside the other ("부채" in "유동부채") counts as different
                label_reason = f"AI가 읽은 계정명 '{label}'과 같은 줄에서 OCR이 읽은 계정명 '{ocr_label}'이 다르다"
            elif _key(label) != _key(ocr_label):
                # close but not the same ("총당부채" for "충당부채"): a typo of one of the two readers; which one cannot
                # be told, and the label is not corrected. Taking it as the same account once let three typos through
                label_reason = f"계정명 표기가 OCR과 조금 다르다 (AI '{label}', OCR '{ocr_label}', 오타일 수 있다)"
            else:
                label_known = True
    for position, printed in enumerate(amounts):
        if position >= len(statement.columns):
            break
        column = position
        try:
            value = parse_amount(printed, unit)
        except ValueError:
            continue
        token = chosen[position]
        if column in row.amounts:
            if row.amounts[column].value != value:  # two overlapping bands read this cell differently
                for check in checks:
                    if (check.statement, check.row, check.column) == (s_index, r_index, column):
                        check.flag(f"겹친 두 띠에서 다른 숫자로 읽었다 ({row.amounts[column].printed}, {printed})")
            if token is not None:
                _claim(token, part.tokens, claimed, r_index)
            continue
        evidence = ("OCR" if label_known else "OCR (숫자만, 계정명 미확인)") if token is not None else ""
        check = CellCheck(s_index, r_index, column, evidence=evidence)
        if token is not None:
            _claim(token, part.tokens, claimed, r_index)
        else:
            check.flag("원본 OCR에서 같은 숫자를 찾지 못했다 (AI만 읽은 숫자)")
        for reason in unsure[position]:
            check.flag(reason)
        if label_reason:
            check.flag(label_reason)
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


def _overlap_row(amounts: Sequence[str], tokens: Sequence[Word], claimed: dict[int, int], first: int,
                 reread: set[int]) -> int | None:
    """The row of the previous band whose OCR token this reading shares: the overlap of two bands. A token
    serves one re-reading per band, so a second row of the same label and value is not folded into the first."""
    for printed in amounts:
        for word in tokens:
            owner = claimed.get(id(word))
            if (owner is not None and owner >= first and id(word) not in reread
                    and _digits(word.text) == _digits(printed)):
                reread.update(id(other) for other in tokens if claimed.get(id(other)) == owner)
                return owner
    return None


def _ai_only_repeat(statement: Statement, label: str, amounts: Sequence[str], tokens: Sequence[Word],
                    claimed: dict[int, int], first: int) -> int | None:
    """A reading with no OCR token at all that repeats a recent row also read by the AI only (same label and
    digits): the overlap again, as far as can be told. A reading with a token of its own is a new row."""
    digits = [_digits(printed) for printed in amounts]
    if any(_digits(word.text) in digits and id(word) not in claimed for word in tokens):
        return None
    for index in range(max(0, first), len(statement.rows)):
        row = statement.rows[index]
        if (_key(row.label) == _key(label) and all(amount.cell.method == "ai" for amount in row.amounts.values())
                and [_digits(row.amounts[column].printed) for column in sorted(row.amounts)] == digits[:len(row.amounts)]):
            return index
    return None


def _row_tokens(amounts: Sequence[str], tokens: Sequence[Word], claimed: dict[int, int],
                owner: int | None = None) -> tuple[list[Word | None], list[list[str]]]:
    """For each amount, an OCR token of the same digits, chosen so that the row's tokens are on one line and in
    period order; with the reasons a choice is not certain. A new row takes unclaimed tokens; a row read again
    in a band overlap (``owner``) takes its own tokens first, never another row's."""
    def usable(word: Word) -> bool:
        holder = claimed.get(id(word))
        return holder is None or (owner is not None and holder == owner)

    candidates = []
    for printed in amounts:
        options = [word for word in tokens if usable(word) and _digits(word.text) == _digits(printed)]
        own = [word for word in options if owner is not None and claimed.get(id(word)) == owner]
        candidates.append(own or options)
    reasons: list[list[str]] = [[] for _ in amounts]
    best: list[Word | None] = [options[0] if options else None for options in candidates]
    found = [index for index, options in enumerate(candidates) if options]
    if len(found) >= 2:
        # the combination whose tokens share a line, left to right
        combos = [[]]
        for index in found:
            combos = [combo + [word] for combo in combos for word in candidates[index]][:200]
        good = [combo for combo in combos if _same_line(combo) and all(a.x0 < b.x0 for a, b in zip(combo, combo[1:]))]
        if good:
            for index, word in zip(found, good[0]):
                best[index] = word
            # the OCR passes read one printed number several times at one place: count places, not readings
            if len({tuple(_place(word, candidates[index]) for index, word in zip(found, combo)) for combo in good}) > 1:
                for index in found:
                    reasons[index].append("같은 숫자들이 띠 안 여러 줄에 있어 어느 줄인지 확정하지 못했다")
        else:
            for index in found:
                reasons[index].append("이 줄의 숫자들을 원본(OCR)의 한 줄에서 찾지 못했다 (다른 줄의 숫자일 수 있다)")
    elif len(found) == 1 and len(candidates[found[0]]) > 1:
        options = candidates[found[0]]
        if any(not _same_line([a, b]) for a in options for b in options):
            reasons[found[0]].append("같은 숫자가 띠 안 여러 줄에 있어 어느 줄인지 확정하지 못했다")
    return best, reasons


def _place(word: Word, readings: Sequence[Word]) -> int:
    """The printed place of a reading: the first of ``readings`` it overlaps (the OCR passes overlap there)."""
    return next(index for index, other in enumerate(readings) if other is word or _overlaps(word, other))


def _same_line(words: Sequence[Word]) -> bool:
    centres = [(word.top + word.bottom) / 2 for word in words]
    height = max(1.0, min(word.bottom - word.top for word in words))
    return max(centres) - min(centres) <= 0.6 * height


def _line_words(chosen: Sequence[Word | None], tokens: Sequence[Word]) -> list[Word] | None:
    """The macOS Vision words with Hangul on the line of the row's first confirmed amount, left of it (its label).
    Tesseract's Hangul on a photo is too noisy to compare ("재고자산워드", two passes read as "이이연법인세부채");
    Vision read the photo's labels cleanly. None when there is no confirmed amount to anchor the line."""
    anchor = next((word for word in chosen if word is not None), None)
    if anchor is None:
        return None
    centre, height = (anchor.top + anchor.bottom) / 2, max(1.0, anchor.bottom - anchor.top)
    words = [word for word in tokens if abs((word.top + word.bottom) / 2 - centre) <= 0.6 * height
             and word.x1 <= anchor.x0 and re.search(r"[가-힣]", word.text)
             and word.line_key is not None and word.line_key[0] == VISION_LINE]
    # the three OCR passes read the same words: keep one reading per position, left to right
    kept: list[Word] = []
    for word in sorted(words, key=lambda w: (w.x0, -(w.confidence or 0))):
        if not any(_overlaps(word, other) for other in kept):
            kept.append(word)
    return kept


def _overlaps(a: Word, b: Word) -> bool:
    width = min(a.x1 - a.x0, b.x1 - b.x0)
    height = min(a.bottom - a.top, b.bottom - b.top)
    if width <= 0 or height <= 0:
        return False
    across = min(a.x1, b.x1) - max(a.x0, b.x0)
    down = min(a.bottom, b.bottom) - max(a.top, b.top)
    return across > 0.5 * width and down > 0.5 * height


def _claim(token: Word, tokens: Sequence[Word], claimed: dict[int, int], r_index: int) -> None:
    """Claim a token and the other OCR passes' readings of the same printed number (same place)."""
    for word in tokens:
        if word is token or (_overlaps(word, token) and _is_amount_word(word.text)):
            claimed.setdefault(id(word), r_index)


def _report_unread_tokens(statement: Statement, part: Part, claimed: dict[int, int]) -> None:
    """OCR amounts on the page that no row of the AI's reading claimed: a row it may have skipped. One report per
    printed place (the OCR passes overlap), and none where any reading of that place was claimed."""
    reported: list[Word] = []
    for word in part.tokens:
        if id(word) in claimed or not _is_amount_word(word.text) or len(_digits(word.text)) < 4:
            continue
        if any(id(other) in claimed and _overlaps(word, other) for other in part.tokens):
            continue
        if any(_overlaps(word, other) for other in reported):
            continue
        reported.append(word)
        statement.problems.append(f"{part.page}쪽: OCR이 읽은 금액 '{word.text}'를 AI가 읽지 않았다 (행이 빠졌을 수 있다)")


def _add_row(statement: Statement, checks: list[CellCheck], s_index: int, item: BandLine, band_lines: Sequence[Line],
             header: Header | None, part: Part, claimed: set[int]) -> None:
    label = clean_label(item.label, ocr=True)
    if not label:
        return
    evidence_line = _match_line(item, band_lines)
    label_problem = None
    if evidence_line is not None:
        words = without_section_column([c for c in evidence_line.cells if re.search(r"[가-힣]", c.text) and not c.is_amount])
        source_label = clean_label(" ".join(c.text for c in words), ocr=True)
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
    existing = _existing_row(statement, evidence_line) if evidence_line is not None else None
    row = statement.rows[existing] if existing is not None else Row(
        label, account_of(label), _label_cell(evidence_line), {})
    regular = [printed for printed in item.amounts if not _is_bare_small(printed)]
    small = [printed for printed in item.amounts if _is_bare_small(printed)]
    for printed in small:
        # "42", "2": an amount only when the page prints it in a period slot of this line; otherwise a note number
        # the model copied, ignored (no flag, no row)
        cell = next((c for c in (evidence_line.cells if evidence_line is not None else ())
                     if _digits(c.text) == _digits(printed) and id(c) not in claimed and header is not None
                     and _is_bare_small(c.text) and _in_free_slot(c, evidence_line, header)), None)
        if cell is not None:
            regular.append(printed)
    for position, printed in enumerate(regular):
        if printed in ("-", "–", "—"):
            continue
        digits = _digits(printed)
        cell = None
        if evidence_line is not None:
            cell = next((c for c in evidence_line.cells if _digits(c.text) == digits and id(c) not in claimed
                         and (_is_amount_word(c.text) or (_is_bare_small(c.text) and header is not None
                                                          and _in_free_slot(c, evidence_line, header)))), None)
        reasons = [label_problem] if label_problem else []
        if cell is not None:
            claimed.add(id(cell))
            column = header.period_of(cell.x1) if header else None
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
            if cell is None or row.amounts[column].cell is cell:
                continue  # the overlap line between two bands, already read
            # two amounts of one printed line in one period: neither is trusted, the second is reported
            r_index = existing if existing is not None else len(statement.rows)
            for check in checks:
                if (check.statement, check.row, check.column) == (s_index, r_index, column):
                    check.flag(f"같은 줄의 다른 금액 '{printed}'도 이 기간으로 읽혀 기간 배정이 불확실하다")
            statement.problems.append(f"{part.page}쪽: '{label}' 줄의 금액 '{printed}'를 기간 열에 넣지 못했다 (원본 확인 필요)")
            continue
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
