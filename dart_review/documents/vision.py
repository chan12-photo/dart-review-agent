"""A vision model that transcribes one band of a statement table into lines "label | amount | amount ...".

The model reads; it is not trusted. Every amount it returns is checked against independent evidence (the
PDF's text layer, or Tesseract on the same image) in ai_reader.py.

Local first (no cost): Ollama with qwen3-vl. Two findings from the first real photo shaped this module:
- qwen3-vl on Ollama 0.34 thinks before answering even with think=false, and on a dense table the thinking
  used the whole output budget. An assistant turn pre-filled with an empty think block makes it answer
  directly (about 5 s per band instead of running out of budget).
- Asked for a whole dense page, the model broke the line format and repeated numbers; asked for a band of
  about eight lines, it read most cells right. So the caller sends bands, not pages.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
import hashlib
import io
import json
import re
import time
from typing import Any, Protocol
import urllib.error
import urllib.request

DEFAULT_VISION_MODEL = "qwen3-vl:8b"
OLLAMA_URL = "http://127.0.0.1:11434"
PROMPT_VERSION = "band-v1"
BAND_PROMPT = (
    "사진은 재무제표 표의 일부다. 보이는 줄을 위에서 아래로 한 줄에 하나씩 옮겨라. "
    "형식: 계정 | 금액 | 금액 (금액은 왼쪽부터 보이는 순서대로, 보이는 글자 그대로: 쉼표와 괄호 포함). "
    "주석 번호는 적지 마라. 금액이 없는 칸은 적지 마라. 잘려서 일부만 보이는 맨 위·맨 아래 줄은 적지 마라. "
    "읽을 수 없는 숫자는 ? 로 적어라. 표 밖의 글은 적지 마라. 추측하지 마라."
)
META_PROMPT = (
    "사진 위쪽에 재무제표의 제목, 회사, 기간, 단위, 표의 열 머리글이 있다. 보이는 글자 그대로 다음 형식으로만 답하라. "
    "없으면 빈칸으로 둬라. 추측하지 마라.\n제목: \n기간: (한 줄에 하나씩)\n단위: \n열: 머리글 | 머리글 | ..."
)
_EMPTY_THINK = "<think>\n\n</think>\n\n"
# an amount: digits grouped by three, or a small one in parentheses or of three digits ("(973)", "682");
# never a note number ("4", "29", "4, 29")
SMALL_OR_GROUPED = re.compile(r"[(（]?[-−△]?\d{1,3}([,.]\d{3})+[)）]?|[(（][-−△]?\d{1,3}[)）]|[-−△]?\d{3}")
AMOUNT = re.compile(r"^(?:[(（]?[-−△]?\d{1,3}(,\d{3})+[)）]?|[(（][-−△]?\d{1,3}[)）]|[-−△]?\d{3})$|^[-–—]$")


class VisionError(Exception):
    """The model could not be asked or gave no usable answer. Never carries document contents."""


class VisionModel(Protocol):
    name: str

    def transcribe(self, png: bytes, prompt: str) -> str: ...


@dataclass
class BandLine:
    label: str
    amounts: list[str]  # as printed, left to right


@dataclass
class OllamaVision:
    """A local Ollama vision model. Records every call (no image bytes, only their hash) for reproducibility."""

    name: str = DEFAULT_VISION_MODEL
    url: str = OLLAMA_URL
    timeout: float = 600.0
    num_predict: int = 2000
    calls: list[dict[str, Any]] = field(default_factory=list)

    def transcribe(self, png: bytes, prompt: str) -> str:
        body = {"model": self.name, "stream": False, "think": False,
                "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(png).decode()]},
                             {"role": "assistant", "content": _EMPTY_THINK}],
                "options": {"temperature": 0, "num_ctx": 16384, "num_predict": self.num_predict}}
        request = urllib.request.Request(f"{self.url}/api/chat", json.dumps(body).encode(),
                                         {"Content-Type": "application/json"})
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise VisionError(f"could not reach the local vision model ({type(exc).__name__}); is Ollama running?") from exc
        content = (reply.get("message") or {}).get("content") or ""
        self.calls.append({"model": self.name, "prompt_version": PROMPT_VERSION,
                           "image_sha256": hashlib.sha256(png).hexdigest(), "seconds": round(time.monotonic() - started, 2),
                           "done_reason": reply.get("done_reason"), "eval_count": reply.get("eval_count"),
                           "answer_sha256": hashlib.sha256(content.encode()).hexdigest()})
        if reply.get("done_reason") == "length":
            raise VisionError("the model ran out of its output budget on one band")
        return content


def ollama_ready(name: str = DEFAULT_VISION_MODEL, url: str = OLLAMA_URL) -> dict[str, Any]:
    """Whether the local Ollama answers and has the model (a quick check for the server's /health)."""
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=2) as response:
            models = {item.get("name") for item in json.load(response).get("models", [])}
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return {"ready": False, "model": name, "reason": "Ollama가 응답하지 않는다 (ollama serve)"}
    if name not in models:
        return {"ready": False, "model": name, "reason": f"모델이 없다 (ollama pull {name})"}
    return {"ready": True, "model": name}


def png_bytes(image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class PageMeta:
    title: str = ""
    periods: list[str] = field(default_factory=list)
    unit: str = ""
    columns: list[str] = field(default_factory=list)


def parse_meta(text: str) -> PageMeta:
    meta = PageMeta()
    for raw in text.splitlines():
        name, _, value = raw.partition(":")
        name, value = name.strip(), value.strip()
        if name == "제목":
            meta.title = value
        elif name == "기간" and value:
            meta.periods.append(value)
        elif name == "단위":
            meta.unit = value
        elif name == "열":
            meta.columns = [part.strip() for part in value.split("|") if part.strip()]
    return meta


def parse_band(text: str) -> list[BandLine]:
    """Lines "label | amount | ..." to (label, amounts). Parts that are not amounts (a note number like "4, 29",
    a "?") are dropped from the amounts; a line without a Hangul label or without any amount is skipped."""
    lines = []
    for raw in text.splitlines():
        parts = [part.strip() for part in raw.strip().strip("|").split("|")]
        label = next((part for part in parts if re.search(r"[가-힣]", part)), None)
        if not label:
            continue
        amounts = [part.replace(" ", "") for part in parts[parts.index(label) + 1:] if AMOUNT.match(part.replace(" ", ""))]
        if amounts:
            lines.append(BandLine(label, amounts))
    return lines
