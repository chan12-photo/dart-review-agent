"""Tests for the OpenDART client, response cache, and key handling (no network)."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile

from dart_review import cache as cache_module
from dart_review.cache import CacheError, ResponseCache
from dart_review.client import DartAPIError, DartClient, DartTransportError, EndpointNotAllowed, NotCached
from dart_review.companies import SealedCompanyError, ensure_not_sealed
from dart_review.credentials import CredentialError, load_key

FAKE_KEY = "0123456789abcdef" * 2 + "01234567"
ROOT = Path(__file__).resolve().parents[1]


def json_body(status="000", message="정상", rows=None):
    return json.dumps({"status": status, "message": message, "list": rows or []}, ensure_ascii=False).encode("utf-8")


def zip_body(name="CORPCODE.xml", text="<result><list><corp_code>00000001</corp_code><corp_name>가상회사</corp_name><stock_code>000001</stock_code></list></result>"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, text)
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class FakeNetwork:
    """Plays back a list of bodies or exceptions and records requested URLs."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return FakeResponse(outcome)


def http_error(code):
    return urllib.error.HTTPError(f"https://opendart.fss.or.kr/api/x?crtfc_key={FAKE_KEY}", code, "error", {}, io.BytesIO(b""))


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = ResponseCache(Path(self.temp.name) / "cache")
        self.key_loads = 0
        self.sleeps = []

    def key_loader(self):
        self.key_loads += 1
        return FAKE_KEY

    def client(self, network, **kwargs):
        return DartClient(self.cache, key_loader=self.key_loader, urlopen=network, sleep=self.sleeps.append, clock=lambda: 0.0, **kwargs)

    def cache_text(self):
        return "".join(p.read_bytes().decode("utf-8", errors="ignore") for p in Path(self.temp.name).rglob("*") if p.is_file())

    def test_ok_response_is_cached_and_reused_without_network(self):
        network = FakeNetwork(json_body(rows=[{"account_id": "ifrs-full_Revenue"}]))
        client = self.client(network)
        first = client.financial_statements("00126380", 2025, "11011", "CFS")
        second = client.financial_statements("00126380", 2025, "11011", "CFS")
        self.assertTrue(first.has_data)
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(client.network_requests, 1)
        self.assertEqual(first.sha256, second.sha256)
        self.assertNotIn(FAKE_KEY, self.cache_text())
        self.assertNotIn("crtfc_key", self.cache_text())

    def test_no_data_is_an_answer_not_an_error(self):
        client = self.client(FakeNetwork(json_body("013", "조회된 데이타가 없습니다.")))
        response = client.financial_statements("00126380", 2014, "11011", "CFS")
        self.assertEqual(response.status, "013")
        self.assertFalse(response.has_data)
        self.assertTrue(client.financial_statements("00126380", 2014, "11011", "CFS").from_cache)

    def test_api_errors_raise_and_are_not_cached_or_retried(self):
        network = FakeNetwork(json_body("020", "요청 제한을 초과하였습니다."), json_body("020", "요청 제한을 초과하였습니다."))
        client = self.client(network)
        for _ in range(2):
            with self.assertRaises(DartAPIError) as caught:
                client.financial_statements("00126380", 2025, "11011", "CFS")
            self.assertEqual(caught.exception.status, "020")
        self.assertEqual(client.network_requests, 2)
        self.assertEqual(list(Path(self.temp.name).rglob("*.meta.json")), [])

    def test_zip_endpoint_success_and_xml_error(self):
        client = self.client(FakeNetwork(zip_body()))
        self.assertEqual(client.corp_codes()[0]["corp_name"], "가상회사")
        failing = DartClient(ResponseCache(Path(self.temp.name) / "other"), key_loader=self.key_loader,
                             urlopen=FakeNetwork("<result><status>010</status><message>등록되지 않은 키입니다.</message></result>".encode("utf-8")),
                             sleep=self.sleeps.append, clock=lambda: 0.0)
        with self.assertRaises(DartAPIError) as caught:
            failing.request("corpCode.xml")
        self.assertEqual(caught.exception.status, "010")

    def test_server_errors_are_retried_client_errors_are_not(self):
        client = self.client(FakeNetwork(http_error(503), json_body()))
        self.assertTrue(client.financial_statements("00126380", 2025, "11011", "CFS").has_data)
        self.assertEqual(client.network_requests, 2)
        client = self.client(FakeNetwork(http_error(400)))
        with self.assertRaises(DartTransportError):
            client.financial_statements("00126380", 2024, "11011", "CFS")
        self.assertEqual(client.network_requests, 1)

    def test_errors_never_carry_the_key(self):
        client = self.client(FakeNetwork(*(urllib.error.URLError(f"failed for crtfc_key={FAKE_KEY}") for _ in range(3))))
        with self.assertRaises(DartTransportError) as caught:
            client.financial_statements("00126380", 2025, "11011", "CFS")
        error = caught.exception
        self.assertEqual(client.network_requests, 3)
        for text in (str(error), repr(error)):
            self.assertNotIn(FAKE_KEY, text)
        self.assertIsNone(error.__cause__)
        self.assertTrue(error.__suppress_context__)

    def test_offline_cache_miss_never_loads_the_key(self):
        client = self.client(FakeNetwork(), offline=True)
        with self.assertRaises(NotCached):
            client.financial_statements("00126380", 2025, "11011", "CFS")
        self.assertEqual(self.key_loads, 0)

    def test_endpoint_allowlist_and_key_parameter_guard(self):
        client = self.client(FakeNetwork())
        with self.assertRaises(EndpointNotAllowed):
            client.request("company.json", corp_code="00126380")
        with self.assertRaises(ValueError):
            client.request("list.json", crtfc_key=FAKE_KEY)
        self.assertEqual(client.network_requests, 0)

    def test_requests_are_spaced_by_min_interval(self):
        # first request records t=0.0; the second sees t=0.1 (0.4 s too early), sleeps, then records t=0.5
        ticks = iter([0.0, 0.1, 0.5])
        client = DartClient(self.cache, key_loader=self.key_loader, urlopen=FakeNetwork(json_body(), json_body()),
                            sleep=self.sleeps.append, clock=lambda: next(ticks), min_interval=0.5)
        client.financial_statements("00126380", 2025, "11011", "CFS")
        client.financial_statements("00126380", 2025, "11011", "OFS")
        self.assertAlmostEqual(self.sleeps[0], 0.4)


class CacheTests(unittest.TestCase):
    def test_tampered_entry_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            cache = ResponseCache(Path(temp))
            cache.put("list.json", {"corp_code": "1"}, b'{"status":"000"}', "000", "정상", "2026-10-07T00:00:00+00:00")
            body = next(Path(temp).rglob("*.body"))
            body.write_bytes(b'{"status":"000","edited":true}')
            with self.assertRaises(CacheError):
                cache.get("list.json", {"corp_code": "1"})

    def test_cache_refuses_key_in_parameters(self):
        with self.assertRaises(ValueError):
            cache_module.entry_id("list.json", {"crtfc_key": FAKE_KEY})


class CredentialTests(unittest.TestCase):
    def test_valid_missing_and_malformed_key_files(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "api_key"
            path.write_text(FAKE_KEY + "\n", encoding="utf-8")
            self.assertEqual(load_key(path), FAKE_KEY)
            path.write_text(FAKE_KEY * 2, encoding="utf-8")
            with self.assertRaises(CredentialError) as caught:
                load_key(path)
            self.assertNotIn(FAKE_KEY, str(caught.exception))
            self.assertIn("80 characters", str(caught.exception))
            with self.assertRaises(CredentialError):
                load_key(Path(temp) / "missing")


class SealedCompanyTests(unittest.TestCase):
    def test_sealed_companies_are_refused(self):
        ensure_not_sealed("00126380")
        with self.assertRaises(SealedCompanyError):
            ensure_not_sealed("00266961")


class PublicSafetyTests(unittest.TestCase):
    def test_phone_numbers_but_not_digits_inside_hex_digests(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import check_public_safety
        pattern = dict(check_public_safety.TEXT_PATTERNS)["korean_phone_number"]
        prefix = "0" + "10"  # assembled so this file does not itself look like it holds a phone number
        for text in (f"연락처 {prefix}-1234-5678", f"{prefix}12345678", f"번호:{prefix}12345678."):
            self.assertTrue(pattern.search(text), text)
        self.assertFalse(pattern.search("76415e813ef7618d0dc90ff2ed65930caa01040247575f4d6e0ae1cb0209cf00"))


    def test_scan_flags_key_parameter_and_real_key_value(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / "leak.txt").write_text("url?crtfc_key=" + "ab" * 10 + "\n", encoding="utf-8")
            (repo / "plain.txt").write_text("value " + FAKE_KEY + "\n", encoding="utf-8")
            key_file = repo.parent / f"{repo.name}_key"
            key_file.write_text(FAKE_KEY, encoding="utf-8")
            self.addCleanup(key_file.unlink)
            env = dict(os.environ, DART_API_KEY_FILE=str(key_file))
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_public_safety.py"), "--root", str(repo)],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("opendart_key_param", result.stdout)
            self.assertIn("plain.txt:0: opendart_key_value", result.stdout)
            self.assertNotIn(FAKE_KEY, result.stdout + result.stderr)
            self.assertNotIn("ab" * 10, result.stdout + result.stderr)  # a matched value is never printed

    def test_history_scan_finds_removed_secrets_without_printing_them(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            git = lambda *args: subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
            git("init", "-q")
            git("config", "user.email", "test@example.com")
            git("config", "user.name", "test")
            leaked = "url?crtfc_key=" + "cd" * 10
            (repo / "notes.txt").write_text(leaked + "\n", encoding="utf-8")
            git("add", "notes.txt")
            git("commit", "-q", "-m", "add notes")
            (repo / "notes.txt").write_text("clean\n", encoding="utf-8")
            git("commit", "-q", "-am", "remove the leak")
            env = dict(os.environ, DART_API_KEY_FILE=str(repo / "missing_key"))
            result = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_history_safety.py"), "--root", str(repo)],
                                    capture_output=True, text=True, env=env)
            self.assertEqual(result.returncode, 1)
            self.assertIn("notes.txt:1: opendart_key_param", result.stdout)
            self.assertNotIn("cd" * 10, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
