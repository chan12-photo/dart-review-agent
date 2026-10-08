"""Build dart_review/company_vocabulary.json: company names that contain a supported name, alias, or group.

Read from OpenDART's company list in the cache (corpCode.xml: names and codes,
no financial data). Only names that contain a development company's name, an
alias, or a group name are kept, so the rules can tell 카카오뱅크 from 카카오
(docs/EVAL_DESIGN.ko.md section 12.3). The supported companies themselves are
left out.

    python scripts/build_company_vocabulary.py          # writes the file
    python scripts/build_company_vocabulary.py --check  # fails if the file is stale
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.companies import DEV_COMPANIES  # noqa: E402

# imported without the vocabulary it is about to build
ALIASES = {"삼전"}
GROUPS = {"삼성"}
CACHE = ROOT / "cache" / "corpCode.xml"
OUT = ROOT / "dart_review" / "company_vocabulary.json"


def normalize(text: str) -> str:
    return "".join((text or "").replace("(주)", "").replace("㈜", "").replace("주식회사", "").split()).casefold()


def build() -> dict:
    bodies = sorted(CACHE.glob("*.body"))
    if len(bodies) != 1:
        raise SystemExit(f"expected one cached company list, found {len(bodies)}")
    with zipfile.ZipFile(bodies[0]) as archive:
        root = ET.fromstring(archive.read(archive.namelist()[0]))
    keys = {normalize(name) for name in DEV_COMPANIES.values()} | {normalize(word) for word in ALIASES | GROUPS}
    supported = {normalize(name) for name in DEV_COMPANIES.values()}
    names, total = set(), 0
    for item in root.iter("list"):
        total += 1
        name = (item.findtext("corp_name") or "").strip()
        if normalize(name) not in supported and any(key in normalize(name) for key in keys):
            names.add(name)
    return {"source": "OpenDART corpCode.xml in the cache (company names only)", "companies_in_list": total,
            "contains": sorted(keys), "names": sorted(names)}


def main(argv: list[str]) -> int:
    if not CACHE.exists():
        print("no cached company list (cache/corpCode.xml)")
        return 2
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        print("company_vocabulary.json is up to date" if current == text else "company_vocabulary.json is stale")
        return 0 if current == text else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(json.loads(text)['names'])} names -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
