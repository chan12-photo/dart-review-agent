"""D4 population order and candidate records (no network: a fake client)."""

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

import d4_population as population  # noqa: E402
import d4_candidates  # noqa: E402

COMPANIES = [
    {"corp_code": "00000001", "corp_name": "가", "stock_code": "000001"},
    {"corp_code": "00000002", "corp_name": "나", "stock_code": " "},  # not listed
    {"corp_code": "00000003", "corp_name": "다", "stock_code": "000003"},
    {"corp_code": "00000004", "corp_name": "라", "stock_code": "000004"},
]


@dataclass
class FakeResponse:
    status: str
    body: bytes
    fetched_at: str = "2026-10-15T00:00:00+00:00"

    @property
    def has_data(self):
        return self.status == "000"

    @property
    def sha256(self):
        return hashlib.sha256(self.body).hexdigest()

    def json(self):
        return json.loads(self.body)

    def zip_members(self):
        archive = zipfile.ZipFile(io.BytesIO(self.body))
        return {name: archive.read(name) for name in archive.namelist()}


class FakeClient:
    def __init__(self, filings_pages=None, induty="264"):
        self.requests, self.filings_pages, self.induty = [], filings_pages, induty

    def request(self, endpoint, **params):
        self.requests.append((endpoint, params))
        if endpoint == "corpCode.xml":
            xml = "<result>" + "".join(f"<list><corp_code>{c['corp_code']}</corp_code><corp_name>{c['corp_name']}</corp_name>"
                                       f"<stock_code>{c['stock_code']}</stock_code></list>" for c in COMPANIES) + "</result>"
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr("CORPCODE.xml", xml)
            return FakeResponse("000", buffer.getvalue())
        if endpoint == "company.json":
            return FakeResponse("000", json.dumps({"status": "000", "induty_code": self.induty}).encode())
        pages = self.filings_pages
        if not pages:
            return FakeResponse("013", b'{"status":"013"}')
        page = pages[params["page_no"] - 1]
        return FakeResponse("000", json.dumps({"status": "000", "total_page": len(pages), "list": page}, ensure_ascii=False).encode())


def filing(number, name="사업보고서 (2025.12)", date="20260315"):
    return {"rcept_no": number, "report_nm": name, "rcept_dt": date, "corp_name": "가", "flr_nm": "가"}


class OrderTests(unittest.TestCase):
    def test_listed_companies_in_seed_order(self):
        record = population.build_order(FakeClient())
        codes = [entry["corp_code"] for entry in record["order"]]
        self.assertEqual(sorted(codes), ["00000001", "00000003", "00000004"])
        expected = sorted(codes, key=lambda code: hashlib.sha256(f"D4-2026|{code}".encode()).hexdigest())
        self.assertEqual(codes, expected)
        self.assertEqual([entry["rank"] for entry in record["order"]], [1, 2, 3])
        self.assertEqual((record["count"], record["source"]["companies"]), (3, 4))

    def test_duplicate_codes_are_refused(self):
        with self.assertRaises(ValueError):
            population.ordered_population(COMPANIES[:1] * 2)


class FetchTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.out = Path(temp.name)
        self.order = population.build_order(FakeClient())

    def test_records_every_page_and_never_overwrites(self):
        client = FakeClient(filings_pages=[[filing("20260315000001")], [filing("20260401000002", "[기재정정]사업보고서 (2025.12)", "20260401")]])
        written = population.fetch(client, self.order, set(), self.out, count=1)
        record = json.loads(written[0].read_text(encoding="utf-8"))
        self.assertEqual([f["rcept_no"] for f in record["filings"]], ["20260315000001", "20260401000002"])
        self.assertEqual(record["induty_code"], "264")
        self.assertEqual(record["attachments"], {})
        params = [p for endpoint, p in client.requests if endpoint == "list.json"]
        self.assertEqual({(p["bgn_de"], p["end_de"], p["pblntf_ty"]) for p in params}, {("20260101", "20260630", "A")})
        written[0].write_text("{}", encoding="utf-8")
        again = population.fetch(FakeClient(), self.order, set(), self.out, count=1)
        self.assertEqual(written[0].read_text(encoding="utf-8"), "{}")
        self.assertNotEqual(again[0], written[0])

    def test_no_filing_is_an_empty_list(self):
        written = population.fetch(FakeClient(filings_pages=None), self.order, set(), self.out, count=1)
        record = json.loads(written[0].read_text(encoding="utf-8"))
        self.assertEqual(record["filings"], [])
        self.assertEqual(d4_candidates.select(record, [])["reason"], "사업보고서 (2025.12) 없음")

    def test_excluded_candidates_make_no_request(self):
        first = self.order["order"][0]["corp_code"]
        client = FakeClient()
        written = population.fetch(client, self.order, {first}, self.out, count=1)
        self.assertEqual(client.requests, [])
        record = json.loads(written[0].read_text(encoding="utf-8"))
        self.assertEqual(d4_candidates.select(record, [first])["decision"], "제외")

    def test_a_fetched_record_feeds_select(self):
        client = FakeClient(filings_pages=[[filing("20260315000001")]])
        record = json.loads(population.fetch(client, self.order, set(), self.out, count=1)[0].read_text(encoding="utf-8"))
        self.assertEqual(d4_candidates.select(record, [])["decision"], "기록 부족")  # attachments are added by hand
        record["attachments"] = {"20260315000001": ["감사보고서", "연결감사보고서", "내부회계관리제도 감사보고서"]}
        self.assertEqual(d4_candidates.select(record, [])["attachment"], {"position": 2, "name": "연결감사보고서"})


if __name__ == "__main__":
    unittest.main()
