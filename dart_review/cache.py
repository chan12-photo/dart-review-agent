"""On-disk cache of raw OpenDART responses.

Each response is stored as the exact bytes received plus a metadata file with
the endpoint, request parameters (never the API key), retrieval time, status,
and SHA-256 of the body. Reads verify the hash so a modified cache entry is
detected instead of silently used.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

KEY_PARAM = "crtfc_key"


class CacheError(Exception):
    pass


@dataclass(frozen=True)
class CachedResponse:
    endpoint: str
    params: dict[str, str]
    body: bytes
    status: str
    message: str
    fetched_at: str
    sha256: str


def _check_params(params: dict[str, Any]) -> dict[str, str]:
    if KEY_PARAM in params:
        raise ValueError("request parameters must not include the API key")
    return {str(k): str(v) for k, v in sorted(params.items())}


def entry_id(endpoint: str, params: dict[str, Any]) -> str:
    payload = json.dumps({"endpoint": endpoint, "params": _check_params(params)}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class ResponseCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _paths(self, endpoint: str, params: dict[str, Any]) -> tuple[Path, Path]:
        base = self.root / endpoint.replace("/", "_") / entry_id(endpoint, params)
        return base.with_suffix(".body"), base.with_suffix(".meta.json")

    def get(self, endpoint: str, params: dict[str, Any]) -> CachedResponse | None:
        body_path, meta_path = self._paths(endpoint, params)
        if not meta_path.exists() or not body_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        body = body_path.read_bytes()
        if hashlib.sha256(body).hexdigest() != meta["sha256"]:
            raise CacheError(f"cache entry {body_path.name} does not match its recorded SHA-256")
        return CachedResponse(meta["endpoint"], meta["params"], body, meta["status"], meta["message"], meta["fetched_at"], meta["sha256"])

    def put(self, endpoint: str, params: dict[str, Any], body: bytes, status: str, message: str, fetched_at: str) -> CachedResponse:
        clean = _check_params(params)
        body_path, meta_path = self._paths(endpoint, params)
        digest = hashlib.sha256(body).hexdigest()
        meta = {"endpoint": endpoint, "params": clean, "status": status, "message": message,
                "fetched_at": fetched_at, "sha256": digest, "size": len(body)}
        _atomic_write(body_path, body)
        _atomic_write(meta_path, (json.dumps(meta, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        return CachedResponse(endpoint, clean, body, status, message, fetched_at, digest)
