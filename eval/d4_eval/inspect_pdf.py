"""Review helpers for the D4 gold (not part of the frozen tools): print a PDF's text lines, or render a page area.

    python eval/d4_eval/inspect_pdf.py lines report.pdf 8 9 [--x]       # lines as eval/d4_gold.py groups them
    python eval/d4_eval/inspect_pdf.py crop report.pdf 8 120 300 out.png  # page 8 from 120 to 300 points, 200dpi

``lines`` prints page, top, and the words of each line (with ``--x``, each word's left and right edge), the same
grouping the gold builder reads. ``crop`` renders the whole page width between two heights, to compare the print
with what the text layer says.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "eval"))


def lines(pdf: Path, first: int, last: int, positions: bool) -> None:
    import d4_gold
    for line in d4_gold.lines_of(pdf):
        if first <= line["page"] <= last:
            words = line["words"]
            text = " ".join(f"{w['text']}[{round(w['x0'])}-{round(w['x1'])}]" if positions else w["text"] for w in words)
            print(line["page"], round(words[0]["top"]), text)


def crop(pdf: Path, page: int, top: float, bottom: float, out: Path, dpi: int = 200) -> None:
    import pypdfium2
    document = pypdfium2.PdfDocument(str(pdf))
    scale = dpi / 72
    image = document[page - 1].render(scale=scale).to_pil()
    image.crop((0, int(top * scale), image.width, int(bottom * scale))).save(out)
    document.close()


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[0] == "lines":
        lines(Path(argv[1]).expanduser(), int(argv[2]), int(argv[3]), "--x" in argv)
        return 0
    if len(argv) == 6 and argv[0] == "crop":
        crop(Path(argv[1]).expanduser(), int(argv[2]), float(argv[3]), float(argv[4]), Path(argv[5]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
