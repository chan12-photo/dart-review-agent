"""D4 synthetic scans (contract 3.3): the statement pages of a text PDF as an image-only PDF, under a fixed condition.

    python eval/d4_scan.py --pdf report.pdf --gold gold.json --condition tilt --out report.tilt.pdf

The pages are those of the gold's statements (each statement's first to last page), each rendered whole (never
cropped) in grey, then turned and blurred as the condition says. Nothing is random: the same PDF and condition give
the same images, so there is no seed. The conditions were set before any scan was read, not tuned on a document.
Next to the PDF goes a map (``<out>.map.json``): the source's SHA-256, the condition, the original page of each
scanned page, and the SHA-256 of the scan and of its pixels. ``scan_gold`` renumbers a confirmed gold by that map,
so the scan is scored against the text PDF's gold (eval/d4_score.py --page-map).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

# contract 3.3 (proposed; the user decides, contract 10.4): 200dpi straight, 150dpi turned 1 degree, 150dpi blurred
CONDITIONS = {"normal": {"dpi": 200, "rotate": 0.0, "blur": 0.0},
              "tilt": {"dpi": 150, "rotate": 1.0, "blur": 0.0},
              "blur": {"dpi": 150, "rotate": 0.0, "blur": 1.2}}


def statement_pages(gold: dict) -> list[int]:
    """The pages of the gold's statements, in order, each once."""
    return sorted({page for s in gold["statements"] for page in range(s["page"], s.get("end_page", s["page"]) + 1)})


def make_scan(source: Path, pages: list[int], condition: str, out: Path) -> dict:
    import pypdfium2
    from PIL import Image, ImageFilter
    spec = CONDITIONS[condition]
    document = pypdfium2.PdfDocument(str(source))
    images = []
    for page in pages:
        image = document[page - 1].render(scale=spec["dpi"] / 72).to_pil().convert("L")
        if spec["rotate"]:
            image = image.rotate(spec["rotate"], resample=Image.BICUBIC, fillcolor=255)
        if spec["blur"]:
            image = image.filter(ImageFilter.GaussianBlur(spec["blur"]))
        images.append(image)
    document.close()
    pixels = hashlib.sha256()
    for image in images:
        pixels.update(f"{image.mode}{image.size}".encode() + image.tobytes())
    # a fixed title and dates: PIL writes the file name and the time of writing otherwise, and the same scan
    # would hash differently
    fixed = time.gmtime(0)
    images[0].save(out, "PDF", resolution=spec["dpi"], save_all=True, append_images=images[1:],
                   title=f"D4 synthetic scan ({condition})", creationDate=fixed, modDate=fixed)
    check = pypdfium2.PdfDocument(str(out))
    count = len(check)
    check.close()
    if count != len(pages):
        raise RuntimeError(f"the scan has {count} pages, not {len(pages)}")
    return {"source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "condition": condition, **spec, "pages": pages, "scan": out.name,
            "scan_sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "pixels_sha256": pixels.hexdigest()}


def scan_gold(gold: dict, page_map: dict) -> dict:
    """A confirmed gold with the scan's page numbers (scan page n is original page pages[n-1])."""
    number = {original: index for index, original in enumerate(page_map["pages"], 1)}
    statements = [{**s, "page": number[s["page"]], "end_page": number[s.get("end_page", s["page"])]}
                  for s in gold["statements"]]
    cells = [{**c, "page": number[c["page"]]} for c in gold["cells"]]
    return {**gold, "statements": statements, "cells": cells, "scan": {k: page_map[k] for k in
                                                                       ("source_sha256", "condition", "scan_sha256")}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True, help="the text PDF's gold: which pages to scan")
    parser.add_argument("--condition", choices=sorted(CONDITIONS), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    record = make_scan(args.pdf, statement_pages(gold), args.condition, args.out)
    args.out.with_name(args.out.name + ".map.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                              encoding="utf-8")
    print(f"{len(record['pages'])} pages ({args.condition}) -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
