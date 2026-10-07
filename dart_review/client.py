"""OpenDART HTTP client with an allowlist, rate limiting, retries, and a response cache.

Guarantees:
- Only allowlisted endpoints are called.
- The API key is read only when a network request is needed, is never stored in
  the cache or returned data, and never appears in raised error messages
  (errors are raised ``from None`` so the original exception, which may carry
  the request URL, is not chained).
- Status ``000`` (normal) and ``013`` (no data) are answers and are cached;
  every other status is an error and is not cached.
- Only transport failures and HTTP 5xx are retried; API status errors such as
  ``020`` (request limit exceeded) are never retried automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import socket
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from .cache import KEY_PARAM, CachedResponse, ResponseCache
from .credentials import load_key

BASE_URL = "https://opendart.fss.or.kr/api/"
# endpoint -> response kind ("json" bodies carry a status field; "zip" bodies
# are archives on success and an XML <result> on failure)
ALLOWED_ENDPOINTS = {
    "corpCode.xml": "zip",
    "fnlttSinglAcntAll.json": "json",
    "list.json": "json",
    "document.xml": "zip",
}
OK = "000"
NO_DATA = "013"
# From the OpenDART development guide (checked 2026-10-07).
STATUS_MESSAGES = {
    "000": "정상",
    "010": "등록되지 않은 키",
    "011": "사용할 수 없는 키",
    "012": "접근할 수 없는 IP",
    "013": "조회된 데이터 없음",
    "014": "파일이 존재하지 않음",
    "020": "요청 제한 초과",
    "021": "조회 가능한 회사 개수 초과",
    "100": "필드의 부적절한 값",
    "101": "부적절한 접근",
    "800": "시스템 점검으로 서비스 중지",
    "900": "정의되지 않은 오류",
    "901": "사용자 계정의 개인정보 보유기간 만료",
}


class DartError(Exception):
    """Base class. Messages never contain the API key."""


class EndpointNotAllowed(DartError):
    pass


class DartAPIError(DartError):
    def __init__(self, endpoint: str, status: str, message: str):
        super().__init__(f"OpenDART {endpoint} returned status {status}: {message}")
        self.endpoint = endpoint
        self.status = status
        self.api_message = message


class DartTransportError(DartError):
    pass


class NotCached(DartError):
    pass


@dataclass(frozen=True)
class DartResponse:
    endpoint: str
    params: dict[str, str]
    status: str
    message: str
    body: bytes
    fetched_at: str
    sha256: str
    from_cache: bool

    @property
    def has_data(self) -> bool:
        return self.status == OK

    def json(self) -> dict[str, Any]:
        return json.loads(self.body)

    def zip_members(self) -> dict[str, bytes]:
        archive = zipfile.ZipFile(io.BytesIO(self.body))
        return {name: archive.read(name) for name in archive.namelist()}


def parse_status(endpoint: str, body: bytes) -> tuple[str, str]:
    kind = ALLOWED_ENDPOINTS[endpoint]
    if kind == "zip" and body[:2] == b"PK":
        return OK, STATUS_MESSAGES[OK]
    if kind == "json":
        try:
            data = json.loads(body)
        except ValueError:
            raise DartTransportError(f"OpenDART {endpoint} returned a body that is not JSON") from None
        status = str(data.get("status", ""))
        return status, str(data.get("message", STATUS_MESSAGES.get(status, "")))
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise DartTransportError(f"OpenDART {endpoint} returned neither an archive nor an XML status") from None
    status = (root.findtext("status") or "").strip()
    return status, (root.findtext("message") or STATUS_MESSAGES.get(status, "")).strip()


class DartClient:
    def __init__(
        self,
        cache: ResponseCache,
        *,
        key_loader: Callable[[], str] = load_key,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        min_interval: float = 0.5,
        max_retries: int = 2,
        timeout: float = 30.0,
        offline: bool = False,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.cache = cache
        self._key_loader = key_loader
        self._key: str | None = None
        self._urlopen = urlopen
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.offline = offline
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.network_requests = 0

    def request(self, endpoint: str, **params: Any) -> DartResponse:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise EndpointNotAllowed(f"endpoint not allowed: {endpoint}")
        if KEY_PARAM in params:
            raise ValueError("pass the API key through the key loader, not as a parameter")
        clean = {str(k): str(v) for k, v in params.items()}
        cached = self.cache.get(endpoint, clean)
        if cached is not None:
            return self._from_cached(cached, from_cache=True)
        if self.offline:
            raise NotCached(f"{endpoint} {clean} is not in the cache and the client is offline")
        body = self._fetch(endpoint, clean)
        status, message = parse_status(endpoint, body)
        if status not in (OK, NO_DATA):
            raise DartAPIError(endpoint, status, message)
        stored = self.cache.put(endpoint, clean, body, status, message, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        return self._from_cached(stored, from_cache=False)

    @staticmethod
    def _from_cached(entry: CachedResponse, *, from_cache: bool) -> DartResponse:
        return DartResponse(entry.endpoint, entry.params, entry.status, entry.message, entry.body,
                            entry.fetched_at, entry.sha256, from_cache)

    def _wait_for_slot(self) -> None:
        if self._last_request is not None:
            remaining = self.min_interval - (self._clock() - self._last_request)
            if remaining > 0:
                self._sleep(remaining)
        self._last_request = self._clock()

    def _fetch(self, endpoint: str, params: dict[str, str]) -> bytes:
        if self._key is None:
            self._key = self._key_loader()
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode({KEY_PARAM: self._key, **params})
        last_problem = "unknown error"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._sleep(min(8.0, 2.0 ** attempt))
            self._wait_for_slot()
            self.network_requests += 1
            try:
                with self._urlopen(url, timeout=self.timeout) as response:
                    return response.read()
            except urllib.error.HTTPError as exc:
                last_problem = f"HTTP {exc.code}"
                if exc.code < 500:
                    break
            except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
                reason = getattr(exc, "reason", exc)
                last_problem = type(reason).__name__ if not isinstance(reason, str) else "network error"
        raise DartTransportError(f"OpenDART {endpoint} request failed after {attempt + 1} attempt(s): {last_problem}") from None

    # Convenience wrappers -------------------------------------------------

    def corp_codes(self) -> list[dict[str, str]]:
        response = self.request("corpCode.xml")
        members = response.zip_members()
        root = ET.fromstring(next(iter(members.values())))
        return [{child.tag: (child.text or "").strip() for child in item} for item in root.findall("list")]

    def financial_statements(self, corp_code: str, year: int, report_code: str, fs_div: str) -> DartResponse:
        return self.request("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(year), reprt_code=report_code, fs_div=fs_div)
