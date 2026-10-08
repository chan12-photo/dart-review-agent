"""Step 4 of the 3-1 contract: fetch the sealed companies' responses into the local cache (needs the user's approval).

Not product code (not frozen): it only fills cache/ (git-ignored) and writes a
manifest of what was fetched, with each response's status, row count, fetch
time, and SHA-256. It prints no amounts.

Scope (docs/EVAL_CONTRACT_3-1.ko.md section 5): the four sealed companies x
the 2014 annual report + every periodic report from 2022 up to the reference
date (2026: the first quarter and half-year reports; the third-quarter report
is not due before November) x consolidated and separate.

    python scripts/fetch_sealed_cache.py --approved
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient, DartError  # noqa: E402
from dart_review.companies import FS_DIVS, REPORT_CODES, SEALED_EVAL_COMPANIES, using_company_set, ensure_not_sealed  # noqa: E402

MANIFEST = ROOT / "eval" / "sealed_3-1" / "fetch_manifest.json"
REPORTS = [(2014, "11011")] + [(year, code) for year in (2022, 2023, 2024, 2025) for code in REPORT_CODES] \
    + [(2026, "11013"), (2026, "11012")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--approved", action="store_true", help="the user approved this fetch in the conversation")
    args = parser.parse_args(argv)
    if not args.approved:
        parser.error("fetching sealed data needs the user's approval (--approved)")
    if MANIFEST.exists():
        parser.error(f"{MANIFEST.relative_to(ROOT)} exists; the sealed fetch is made once")
    client = DartClient(ResponseCache(ROOT / "cache"))
    entries, counts = [], Counter()
    with using_company_set("sealed-3-1"):
        listed = {row["corp_code"]: row for row in client.corp_codes() if row.get("stock_code")}
        for corp_code, name in SEALED_EVAL_COMPANIES.items():
            ensure_not_sealed(corp_code)  # passes only inside the evaluation set
            if listed.get(corp_code, {}).get("corp_name") != name:
                raise SystemExit(f"company code {corp_code} does not match {name} in the OpenDART list")
            for year, report_code in REPORTS:
                for fs_div in FS_DIVS:
                    label = f"{name} {year} {REPORT_CODES[report_code]} {FS_DIVS[fs_div]}"
                    try:
                        response = client.financial_statements(corp_code, year, report_code, fs_div)
                    except DartError as exc:
                        counts["error"] += 1
                        print(f"ERROR {label}: {type(exc).__name__}")
                        entries.append({"corp_code": corp_code, "year": year, "report_code": report_code,
                                        "fs_div": fs_div, "error": type(exc).__name__})
                        continue
                    rows = len(response.json().get("list", [])) if response.has_data else 0
                    counts[response.status] += 1
                    entries.append({"corp_code": corp_code, "year": year, "report_code": report_code, "fs_div": fs_div,
                                    "status": response.status, "rows": rows, "sha256": response.sha256})
                    print(f"{label}: status {response.status}, rows {rows}")
    MANIFEST.write_text(json.dumps({"reference_date": date.today().isoformat(), "requests": len(entries),
                                    "network_requests": client.network_requests, "status_counts": dict(counts),
                                    "entries": entries}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nstatus counts: {dict(counts)} | network requests: {client.network_requests} | manifest: {MANIFEST.relative_to(ROOT)}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
