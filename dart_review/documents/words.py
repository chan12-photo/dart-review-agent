"""Words with their positions, from a text PDF (pdfplumber) or a scanned page (Tesseract).

Everything after this module works on ``Word`` only, so a text PDF and a scan go through the same table
and statement code. Coordinates are PDF points, origin top-left, on every page.

The libraries are imported only here and only when used: the rest of dart_review keeps to the standard library.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
from pathlib import Path
import shutil
import subprocess
from typing import Iterator, Sequence

OCR_DPI = 300
OCR_LANGUAGES = "kor+eng"


@dataclass(frozen=True)
class Word:
    text: str
    page: int  # 1-based
    x0: float
    x1: float
    top: float
    bottom: float
    method: str = "text"  # "text" (the PDF's own text layer) or "ocr"
    confidence: float | None = None  # OCR confidence 0-100; None for the text layer
    line_key: tuple[int, ...] | None = None  # OCR: Tesseract's (block, paragraph, line); it follows a tilted line

    @property
    def middle(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return self.bottom - self.top


class DocumentError(Exception):
    """The document cannot be read (not a PDF, encrypted, no OCR engine, ...). Never carries file contents."""


def text_layer_words(path: Path) -> list[Word]:
    """Words of the PDF's own text layer, page by page."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise DocumentError("pdfplumber is not installed: pip install -e '.[docs]'") from exc
    words: list[Word] = []
    try:
        with pdfplumber.open(path) as pdf:
            for number, page in enumerate(pdf.pages, 1):
                for item in page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5):
                    words.append(Word(item["text"], number, float(item["x0"]), float(item["x1"]),
                                      float(item["top"]), float(item["bottom"])))
    except Exception as exc:  # pdfminer raises many kinds; the caller only needs to know the file failed
        raise DocumentError(f"cannot read the PDF: {type(exc).__name__}") from exc
    return words


def page_count(path: Path) -> int:
    import pypdfium2
    document = pypdfium2.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


def ocr_words(path: Path, pages: list[int] | None = None, dpi: int = OCR_DPI) -> list[Word]:
    """Words read by Tesseract from rendered pages, with their confidence, in PDF points."""
    if not shutil.which("tesseract"):
        raise DocumentError("tesseract is not installed (brew install tesseract tesseract-lang)")
    try:
        import pypdfium2
    except ImportError as exc:
        raise DocumentError("pypdfium2 is not installed: pip install -e '.[docs]'") from exc
    document = pypdfium2.PdfDocument(str(path))
    words: list[Word] = []
    try:
        for index in range(len(document)):
            if pages and index + 1 not in pages:
                continue
            image = document[index].render(scale=dpi / 72).to_pil()
            words += image_words(image, index + 1, scale=72 / dpi)
    finally:
        document.close()
    return words


def skew_angle(image, limit: float = 3.0, step: float = 0.1) -> float:
    """The rotation (degrees) that makes the text lines horizontal: the angle whose row profile is sharpest.

    Each candidate rotation of a reduced, gray copy is squeezed to one column (the average ink of every pixel
    row); level text lines give alternating dark and light rows, so the sum of squared differences between
    neighbouring rows is largest at the right angle. Pillow only.
    """
    from PIL import Image
    small = image.convert("L")
    small = small.resize((max(1, small.width // 4), max(1, small.height // 4)))
    best, best_score = 0.0, -1.0
    steps = int(round(limit / step))
    for index in range(-steps, steps + 1):
        angle = index * step
        rows = list(small.rotate(angle, fillcolor=255, resample=Image.BILINEAR).resize((1, small.height), Image.BOX).getdata())
        score = sum((rows[i] - rows[i + 1]) ** 2 for i in range(len(rows) - 1))
        if score > best_score:
            best, best_score = angle, score
    return best


def image_words(image, page: int, scale: float = 1.0, level: bool = True, psm: int = 6) -> list[Word]:
    """Tesseract's words for one page image, after levelling it; ``scale`` turns pixels into PDF points.

    ``level`` False: the caller has levelled the image already and needs positions in that same image."""
    from PIL import Image
    angle = skew_angle(image) if level else 0.0
    if angle:
        image = image.convert("L").rotate(angle, fillcolor=255, resample=Image.BICUBIC)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    result = subprocess.run(["tesseract", "stdin", "stdout", "-l", OCR_LANGUAGES, "--psm", str(psm), "tsv"],
                            input=buffer.getvalue(), capture_output=True, check=False)
    if result.returncode != 0:
        raise DocumentError(f"tesseract failed with exit code {result.returncode}")
    return list(_tsv_words(result.stdout.decode("utf-8", errors="replace"), page, scale))


def _tsv_words(tsv: str, page: int, scale: float) -> Iterator[Word]:
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        if not text or row.get("level") != "5":
            continue
        left, top, width, height = (float(row[key]) for key in ("left", "top", "width", "height"))
        yield Word(text, page, left * scale, (left + width) * scale, top * scale, (top + height) * scale,
                   method="ocr", confidence=float(row["conf"]),
                   line_key=(int(row["block_num"]), int(row["par_num"]), int(row["line_num"])))


VISION_SCRIPT = Path(__file__).with_name("vision_ocr.swift")


def vision_available() -> bool:
    import sys
    return sys.platform == "darwin" and shutil.which("swift") is not None and VISION_SCRIPT.exists()


def vision_words(image, page: int) -> list[Word]:
    """macOS Vision's text for one image, as words in image pixels (a second OCR, used only as evidence).

    Vision returns phrases; each is split at spaces and the pieces get x positions in proportion to their
    characters. Confidence is Vision's 0-1 score times 100, comparable in direction (not in scale) to Tesseract's.
    """
    import tempfile
    if not vision_available():
        return []
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "page.png"
        image.save(target)
        result = subprocess.run(["swift", str(VISION_SCRIPT), str(target)], capture_output=True, timeout=300, check=False)
    if result.returncode != 0:
        return []
    words = []
    width, height = image.size
    for number, row in enumerate(result.stdout.decode("utf-8", errors="replace").splitlines()):
        fields = row.split("\t", 5)
        if len(fields) != 6:
            continue
        min_x, min_y, max_x, max_y, confidence = (float(value) for value in fields[:5])
        text = fields[5].strip()
        left, right = min_x * width, max_x * width
        top, bottom = (1 - max_y) * height, (1 - min_y) * height
        pieces = text.split()
        total = max(1, sum(len(piece) for piece in pieces) + len(pieces) - 1)
        cursor = 0
        for piece in pieces:
            x0 = left + (right - left) * cursor / total
            x1 = left + (right - left) * (cursor + len(piece)) / total
            words.append(Word(piece, page, x0, x1, top, bottom, "ocr", confidence * 100, (900, number, 0)))
            cursor += len(piece) + 1
    return words


def read_words(path: Path, ocr: str = "auto", pages: Sequence[int] | None = None) -> list[Word]:
    """``ocr``: "never" (text layer only), "always", or "auto" (OCR the pages whose text layer is empty).
    ``pages``: only these page numbers (1-based); all pages when None."""
    if ocr not in ("auto", "always", "never"):
        raise ValueError(f"ocr must be auto, always, or never, not {ocr!r}")
    wanted = list(pages) if pages else list(range(1, page_count(path) + 1))
    if ocr == "always":
        return ocr_words(path, wanted)
    words = [word for word in text_layer_words(path) if word.page in wanted]
    if ocr == "never":
        return words
    with_text = {word.page for word in words}
    missing = [page for page in wanted if page not in with_text]
    return words + (ocr_words(path, missing) if missing else [])
