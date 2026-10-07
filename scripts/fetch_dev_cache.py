"""Fill the local response cache for the development companies.

Fetches the company code list, every (year, report, consolidated/separate)
combination for the development companies, and a few extra responses the
development questions rely on (EXTRA_REQUESTS). Sealed evaluation companies
are refused. Cached entries are reused, so the script can be re-run safely.

    python scripts/fetch_dev_cache.py --years 2023 2024 2025
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient, DartError  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS, REPORT_CODES, ensure_not_sealed  # noqa: E402


# (corp_code, year, report_code, fs_div, why)
EXTRA_REQUESTS = [
    ("00126380", 2014, "11011", "CFS", "no-data case: OpenDART has no financial statements before 2015"),
]


def fetch(client: DartClient, counts: Counter[str], corp_code: str, year: int, report_code: str, fs_div: str) -> None:
    ensure_not_sealed(corp_code)
    label = f"{DEV_COMPANIES[corp_code]} {year} {REPORT_CODES[report_code]} {FS_DIVS[fs_div]}"
    try:
        response = client.financial_statements(corp_code, year, report_code, fs_div)
    except DartError as exc:
        counts["error"] += 1
        print(f"ERROR {label}: {exc}")
        return
    rows = len(response.json().get("list", [])) if response.has_data else 0
    counts[response.status] += 1
    print(f"{label}: status {response.status} rows {rows} {'(cache)' if response.from_cache else ''}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, nargs="+", default=[2023, 2024, 2025])
    parser.add_argument("--cache", type=Path, default=ROOT / "cache")
    args = parser.parse_args(argv)
    client = DartClient(ResponseCache(args.cache))
    listed = {row["corp_code"]: row for row in client.corp_codes() if row.get("stock_code")}
    counts: Counter[str] = Counter()
    for corp_code, name in DEV_COMPANIES.items():
        ensure_not_sealed(corp_code)
        if listed.get(corp_code, {}).get("corp_name") != name:
            raise SystemExit(f"company code {corp_code} does not match {name} in the OpenDART list")
        for year in args.years:
            for report_code in REPORT_CODES:
                for fs_div in FS_DIVS:
                    fetch(client, counts, corp_code, year, report_code, fs_div)
    for corp_code, year, report_code, fs_div, why in EXTRA_REQUESTS:
        print(f"extra ({why}):", end=" ")
        fetch(client, counts, corp_code, year, report_code, fs_div)
    print(f"\nstatus counts: {dict(counts)} | network requests this run: {client.network_requests}")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
