"""Build dart_review/account_vocabulary.json: the account names seen in the development cache.

The keyword rules (dart_review/baseline.py) use it to tell a supported account
from a longer account name that merely contains a supported keyword, such as
유동자산 (contains 자산) or 매출원가 (contains 매출). Review B7/C1, 2026-10-08.

Only names are kept, normalized to Hangul with parenthesized parts removed
("당기순이익(손실)" -> "당기순이익"); no amounts. The cache holds the three
development companies only, so no evaluation company contributes a name.

    python scripts/build_account_vocabulary.py          # writes the file
    python scripts/build_account_vocabulary.py --check  # fails if the file is stale
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.accounts import normalize_term  # noqa: E402
from dart_review.companies import DEV_COMPANIES  # noqa: E402

CACHE = ROOT / "cache" / "fnlttSinglAcntAll.json"
OUT = ROOT / "dart_review" / "account_vocabulary.json"


def build() -> dict:
    names, statements = set(), 0
    for meta_path in sorted(CACHE.glob("*.meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta["status"] != "000":
            continue
        if meta["params"]["corp_code"] not in DEV_COMPANIES:
            raise SystemExit(f"not a development company in the cache: {meta['params']['corp_code']}")
        body = json.loads(meta_path.with_name(meta_path.name.replace(".meta.json", ".body")).read_text(encoding="utf-8"))
        statements += 1
        names.update(normalize_term(row.get("account_nm", "")) for row in body.get("list", []))
    names.discard("")
    return {"source": "development cache, fnlttSinglAcntAll.json (account_nm only, normalized)",
            "statements": statements, "names": sorted(names)}


def main(argv: list[str]) -> int:
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        print("account_vocabulary.json is up to date" if current == text else "account_vocabulary.json is stale")
        return 0 if current == text else 1
    OUT.write_text(text, encoding="utf-8")
    print(f"{len(json.loads(text)['names'])} names from {json.loads(text)['statements']} statements -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
