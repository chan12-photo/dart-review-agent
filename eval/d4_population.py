"""D4 population and candidate inputs (contract 3.1 and 3.2 steps 2-3), fixed at step ④ before any candidate is opened.

    python eval/d4_population.py order --out eval/d4_population.json            # step ④: fetch and order
    python eval/d4_population.py fetch --population eval/d4_population.json \\
        --excluded eval/d4_excluded.json --count 5 --out-dir eval/d4_candidates   # step ⑤: the next candidates

``order`` fetches OpenDART's company list (``corpCode.xml``) into its own cache folder (``cache/d4``, so the 2026-10-07
copy is not reused), keeps the companies with a stock code, and sorts them by ``sha256("D4-2026|" + corp_code)``.
It records when the list was fetched, the SHA-256 of the response and of the XML inside it, the seed, and the whole
ordered list. Nothing in the order depends on what a company's documents look like.

``fetch`` walks the order and, for each candidate that is not excluded, records the inputs of
``eval/d4_candidates.py select``: the industry code of ``company.json`` and every regular filing in ``list.json``
received from 2026-01-01 to 2026-06-30 (every page). A candidate's record is written once and never overwritten; a
list with no filing (status 013) is recorded as an empty list, which ``select`` tells apart from a missing one. The
attachment names are added by hand from the DART web page (contract 3.2 step 4), in the order DART shows them.
Excluded candidates get a record without any request. It stops after ``--count`` new records.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SEED = "D4-2026|"
LIST_PERIOD = ("20260101", "20260630")  # contract 3.2 step 3


def order_key(corp_code: str) -> str:
    return hashlib.sha256((SEED + corp_code).encode("utf-8")).hexdigest()


def ordered_population(companies: list[dict[str, str]]) -> list[dict[str, Any]]:
    """The companies with a stock code, in seed order (ties cannot happen: corp codes are unique)."""
    listed = [c for c in companies if (c.get("stock_code") or "").strip()]
    codes = [c["corp_code"] for c in listed]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate corp codes in the company list")
    ranked = sorted(listed, key=lambda c: order_key(c["corp_code"]))
    return [{"rank": rank, "corp_code": c["corp_code"], "corp_name": c.get("corp_name", ""),
             "stock_code": c["stock_code"].strip(), "key": order_key(c["corp_code"])}
            for rank, c in enumerate(ranked, 1)]


def build_order(client: Any) -> dict[str, Any]:
    response = client.request("corpCode.xml")
    members = response.zip_members()
    if len(members) != 1:
        raise ValueError(f"expected one file in corpCode.xml, got {sorted(members)}")
    (name, xml), = members.items()
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml)
    companies = [{child.tag: (child.text or "").strip() for child in item} for item in root.findall("list")]
    order = ordered_population(companies)
    return {"source": {"endpoint": "corpCode.xml", "fetched_at": response.fetched_at, "response_sha256": response.sha256,
                       "member": name, "member_sha256": hashlib.sha256(xml).hexdigest(), "companies": len(companies)},
            "seed": SEED, "rule": 'sha256(seed + corp_code) ascending, companies with a stock code (contract 3.1)',
            "count": len(order), "order": order}


def _filings(client: Any, corp_code: str) -> tuple[list[dict[str, Any]], list[str]]:
    filings, fetched, page = [], [], 1
    while True:
        response = client.request("list.json", corp_code=corp_code, bgn_de=LIST_PERIOD[0], end_de=LIST_PERIOD[1],
                                  pblntf_ty="A", last_reprt_at="N", page_no=page, page_count=100)
        fetched.append(response.fetched_at)
        if not response.has_data:  # 013: no filing in the period
            return filings, fetched
        data = response.json()
        filings += [{key: item.get(key) for key in ("rcept_no", "report_nm", "rcept_dt", "corp_name", "flr_nm")}
                    for item in data.get("list", [])]
        if page >= int(data.get("total_page") or 1):
            return filings, fetched
        page += 1


def candidate_record(client: Any, entry: dict[str, Any], excluded: set[str]) -> dict[str, Any]:
    record: dict[str, Any] = {"rank": entry["rank"], "corp_code": entry["corp_code"], "corp_name": entry["corp_name"],
                              "stock_code": entry["stock_code"]}
    if entry["corp_code"] in excluded:
        return record | {"note": "excluded at step ④: nothing requested"}
    company = client.request("company.json", corp_code=entry["corp_code"])
    record |= {"induty_code": company.json().get("induty_code") if company.has_data else None,
               "company_fetched_at": company.fetched_at, "company_status": company.status}
    filings, fetched = _filings(client, entry["corp_code"])
    return record | {"filings": filings, "list_fetched_at": fetched, "attachments": {}}


def fetch(client: Any, population: dict[str, Any], excluded: set[str], out_dir: Path, count: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in population["order"]:
        if len(written) >= count:
            break
        path = out_dir / f"{entry['rank']:05d}_{entry['corp_code']}.json"
        if path.exists():
            continue  # recorded before: never overwritten
        record = candidate_record(client, entry, excluded) | {"recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    from dart_review.cache import ResponseCache
    from dart_review.client import DartClient
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("order")
    make.add_argument("--out", type=Path, required=True)
    get = commands.add_parser("fetch")
    get.add_argument("--population", type=Path, required=True)
    get.add_argument("--excluded", type=Path, required=True)
    get.add_argument("--count", type=int, required=True)
    get.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    client = DartClient(ResponseCache(ROOT / "cache" / "d4"))
    if args.command == "order":
        if args.out.exists():
            parser.error(f"{args.out} exists; the population is fixed once")
        record = build_order(client)
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"{record['count']} companies with a stock code (of {record['source']['companies']}); "
              f"list sha256 {record['source']['response_sha256'][:12]}; requests {client.network_requests}")
        return 0
    population = json.loads(args.population.read_text(encoding="utf-8"))
    excluded = set(json.loads(args.excluded.read_text(encoding="utf-8")))
    for path in fetch(client, population, excluded, args.out_dir, args.count):
        print(path.name)
    print(f"requests {client.network_requests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
