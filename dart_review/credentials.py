"""Load the OpenDART API key from a local file outside the repository."""

from __future__ import annotations

import os
from pathlib import Path
import re

DEFAULT_KEY_PATH = Path.home() / ".config" / "opendart" / "api_key"
KEY_PATTERN = re.compile(r"[0-9a-fA-F]{40}")


class CredentialError(Exception):
    """Raised when the key file is missing or malformed. Never contains the key."""


def key_path() -> Path:
    override = os.environ.get("DART_API_KEY_FILE")
    return Path(override).expanduser() if override else DEFAULT_KEY_PATH


def load_key(path: Path | None = None) -> str:
    path = path or key_path()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise CredentialError(f"OpenDART key file not found: {path}") from None
    except OSError as exc:
        raise CredentialError(f"cannot read OpenDART key file {path}: {type(exc).__name__}") from None
    if not KEY_PATTERN.fullmatch(value):
        raise CredentialError(f"OpenDART key file {path} does not hold one 40-character hex key (found {len(value)} characters)")
    return value
