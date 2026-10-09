"""Sample statement PDFs whose every value is known, for tests and the accuracy evaluation.

- ``text_pdf``: a PDF with a real text layer, written with the standard library. The Korean font is the
  standard CID font HYSMyeongJo-Medium (Adobe-Korea1), referenced and not embedded, so no font file is
  copied into the PDF.
- ``scan_pdf``: the same table drawn into an image (slightly rotated and blurred, as a scan), wrapped in a
  PDF without any text layer, so only OCR can read it. Needs Pillow and a Korean system font.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PAGE_WIDTH, PAGE_HEIGHT = 595, 842  # A4 in points


@dataclass
class SampleStatement:
    title: str  # "재무상태표"
    company: str
    period_lines: list[str]  # "제 56 기 2025년 12월 31일 현재", ...
    unit: str  # "원", "천원", "백만원"
    headers: list[str]  # number-column headers: ["제 56 (당) 기", "제 55 (전) 기"]
    rows: list[tuple[str, list[str]]]  # (label, printed amounts)


def _layout(statement: SampleStatement, size: float = 9.0) -> list[tuple[float, float, str, str]]:
    """(x, y-from-top, text, align) for every string on the page; amounts are right-aligned."""
    items = [(PAGE_WIDTH / 2, 60, statement.title, "center"), (PAGE_WIDTH / 2, 78, statement.company, "center")]
    y = 96
    for line in statement.period_lines:
        items.append((PAGE_WIDTH / 2, y, line, "center"))
        y += 14
    items.append((PAGE_WIDTH - 50, y + 6, f"(단위: {statement.unit})", "right"))
    y += 30
    rights = [PAGE_WIDTH - 50 - 150 * (len(statement.headers) - 1 - i) for i in range(len(statement.headers))]
    items.append((60, y, "과 목", "left"))
    for right, header in zip(rights, statement.headers):
        items.append((right, y, header, "right"))
    y += 22
    for label, amounts in statement.rows:
        items.append((60, y, label, "left"))
        for right, amount in zip(rights, amounts):
            items.append((right, y, amount, "right"))
        y += 16
    return items


def text_pdf(path: Path, statements: Sequence[SampleStatement], size: float = 9.0) -> None:
    pages = []
    for statement in statements:
        commands = []
        for x, y, text, align in _layout(statement, size):
            width = len(text) * size  # the referenced font has a default width of one em per character
            left = x - width if align == "right" else x - width / 2 if align == "center" else x
            hex_text = text.encode("utf-16-be").hex().upper()
            commands.append(f"BT /F1 {size} Tf 1 0 0 1 {left:.2f} {PAGE_HEIGHT - y:.2f} Tm <{hex_text}> Tj ET")
        pages.append("\n".join(commands).encode("ascii"))
    objects: list[bytes] = []
    font_id, cid_id, descriptor_id = 3, 4, 5
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    first_page = 6
    kids = " ".join(f"{first_page + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(f"<< /Type /Font /Subtype /Type0 /BaseFont /HYSMyeongJo-Medium /Encoding /UniKS-UCS2-H "
                   f"/DescendantFonts [{cid_id} 0 R] >>".encode())
    objects.append(f"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /HYSMyeongJo-Medium /CIDSystemInfo "
                   f"<< /Registry (Adobe) /Ordering (Korea1) /Supplement 1 >> /FontDescriptor {descriptor_id} 0 R "
                   f"/DW 1000 >>".encode())
    objects.append(b"<< /Type /FontDescriptor /FontName /HYSMyeongJo-Medium /Flags 6 /FontBBox [0 -148 1001 880] "
                   b"/ItalicAngle 0 /Ascent 880 /Descent -148 /CapHeight 880 /StemV 91 >>")
    for index, content in enumerate(pages):
        page_id = first_page + 2 * index
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                       f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {page_id + 1} 0 R >>".encode())
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    Path(path).write_bytes(bytes(out))


KOREAN_FONTS = ("/System/Library/Fonts/AppleSDGothicNeo.ttc", "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")


def korean_font() -> str | None:
    return next((font for font in KOREAN_FONTS if Path(font).exists()), None)


def scan_pdf(path: Path, statements: Sequence[SampleStatement], dpi: int = 200, rotate: float = 0.6,
             blur: float = 0.6) -> None:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    font_file = korean_font()
    if not font_file:
        raise RuntimeError("no Korean font found for drawing a sample scan")
    scale = dpi / 72
    images = []
    for statement in statements:
        image = Image.new("L", (int(PAGE_WIDTH * scale), int(PAGE_HEIGHT * scale)), 255)
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_file, int(10 * scale))
        for x, y, text, align in _layout(statement):
            width = draw.textlength(text, font=font)
            left = x * scale - width if align == "right" else x * scale - width / 2 if align == "center" else x * scale
            draw.text((left, y * scale - 10 * scale), text, font=font, fill=0)
        image = image.rotate(rotate, fillcolor=255, resample=Image.BICUBIC)
        images.append(image.filter(ImageFilter.GaussianBlur(blur)) if blur else image)
    images[0].save(path, "PDF", resolution=dpi, save_all=True, append_images=images[1:])
