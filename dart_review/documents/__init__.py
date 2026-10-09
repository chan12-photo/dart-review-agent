"""Documents to verified spreadsheets: read statement tables from text or scanned PDFs, check every value,
and write a workbook that keeps where each value came from (v0.2 feature, optional dependencies).

    from dart_review.documents import extract
    result = extract(Path("report.pdf"), Path("report.xlsx"))
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .statement import Statement, find_statements
from .table import group_lines
from .verify import REVIEW, CellCheck, check
from .words import DocumentError, read_words


LOW_PAGE_CONFIDENCE = 70.0  # a page whose OCR words average below this was mostly not read


@dataclass
class Extraction:
    statements: list[Statement]
    checks: list[CellCheck]
    pages_by_method: dict[str, list[int]]
    problems: list[str]  # about the whole document, e.g. amounts found but no statement title

    @property
    def needs_review(self) -> int:
        return sum(item.status == REVIEW for item in self.checks)


def extract(source: Path, workbook: Path | None = None, ocr: str = "auto", reader: str = "rules",
            model=None, pages=None) -> Extraction:
    """``reader``: "rules" (positions and rules only) or "ai" (a vision model reads, the evidence confirms).
    ``model``: the vision model for "ai" (default: local Ollama qwen3-vl)."""
    if reader == "ai":
        return _extract_ai(source, workbook, model, pages)
    words = read_words(source, ocr)
    if not words:
        raise DocumentError("no text was found (the scan may be empty or unreadable)")
    lines = group_lines(words)
    statements = find_statements(lines)
    checks = check(statements)
    problems = []
    amounts = sum(cell.is_amount for line in lines for cell in line.cells)
    if not statements and amounts:
        problems.append(f"재무제표 제목을 찾지 못했다: 금액처럼 보이는 글자 {amounts}개를 표로 옮기지 않았다 (원본 확인 필요)")
    for page in sorted({word.page for word in words if word.method == "ocr"}):
        scores = [word.confidence for word in words if word.page == page and word.confidence is not None
                  and word.confidence >= 0]
        if scores and sum(scores) / len(scores) < LOW_PAGE_CONFIDENCE:
            problems.append(f"{page}쪽 스캔 품질이 낮다 (OCR 평균 확신도 {sum(scores) / len(scores):.0f}): "
                            "읽지 못한 줄이나 칸이 많을 수 있다")
    methods: dict[str, list[int]] = {}
    for word in words:
        pages = methods.setdefault(word.method, [])
        if word.page not in pages:
            pages.append(word.page)
    if workbook is not None:
        from .excel import write_workbook
        write_workbook(workbook, statements, checks, source.name, problems)
    return Extraction(statements, checks, methods, problems)


def _extract_ai(source: Path, workbook: Path | None, model, pages) -> Extraction:
    from .ai_reader import read_document
    from .vision import OllamaVision
    model = model or OllamaVision()
    reading = read_document(source, model, pages)
    if not reading.statements:
        reading.problems.append("재무제표 제목을 찾지 못했다 (AI 읽기를 하지 않았다)")
    sources = {check.evidence for check in reading.checks if check.evidence}
    if workbook is not None:
        from .excel import write_workbook
        write_workbook(workbook, reading.statements, reading.checks, source.name, reading.problems, reader="ai")
    return Extraction(reading.statements, reading.checks, {"ai": sorted({s.page for s in reading.statements})},
                      reading.problems + [f"AI 호출 {reading.calls}번, 증거: {', '.join(sorted(sources)) or '없음'}"])


__all__ = ["DocumentError", "Extraction", "extract"]
