"""Chat with a local Ollama model, and a scripted stand-in for tests.

Only http://127.0.0.1:11434 is used: no other host, no proxy, no redirects
(adapted from local-agent-lab's adapter). ``truncate`` is false so Ollama
should reject an oversized conversation instead of silently dropping older
messages (what the runtime actually does is checked in roadmap 1-5).

Every chat attempt, successful or not, leaves ``last_exchange``: the exact
payload sent and its SHA-256, the raw server response (or the error), and
the elapsed time. ``attempts`` counts requests sent, ``responses`` counts
complete replies.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import hashlib
import json
import socket
import time
from typing import Any, Callable, Sequence
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OPTIONS = {"temperature": 0, "num_ctx": 8192, "num_predict": 4096}
CHAT_FLAGS = {"truncate": False, "shift": False}
MAX_RESPONSE_BYTES = 4 * 1024 * 1024


class ModelError(Exception):
    pass


@dataclass
class Reply:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    thinking: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def message(self) -> dict[str, Any]:
        """The assistant message to append to the conversation."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content}
        if self.thinking:
            message["thinking"] = self.thinking
        if self.tool_calls:
            message["tool_calls"] = copy.deepcopy(self.tool_calls)
        return message


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class OllamaChat:
    def __init__(self, model: str, *, options: dict[str, Any] | None = None, think: Any = None,
                 timeout: float = 600, opener: Any = None, clock: Callable[[], float] = time.monotonic):
        if not model or not model.strip():
            raise ValueError("model name is required")
        self.model = model
        self.options = dict(DEFAULT_OPTIONS if options is None else options)
        self.think = think  # None: not sent, the model's default applies
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        self.clock = clock
        self.model_info: dict[str, Any] | None = None
        self.runtime_version: str | None = None
        self.attempts = 0
        self.responses = 0
        self.last_exchange: dict[str, Any] | None = None

    def _request(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(BASE_URL + path, data=data, method="GET" if data is None else "POST",
                                         headers={"Content-Type": "application/json", "Accept": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if getattr(response, "url", BASE_URL + path) != BASE_URL + path:
                    raise ModelError("redirects from the local server are not allowed")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            body = exc.read(4096).decode("utf-8", errors="replace") if exc.fp else ""
            raise ModelError(f"Ollama returned HTTP {exc.code}: {body}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
            raise ModelError(f"could not reach the local Ollama server: {type(exc).__name__}") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ModelError("the local model response is too large")
        try:
            data = json.loads(raw)
        except ValueError:
            raise ModelError("the local server did not return JSON") from None
        if not isinstance(data, dict):
            raise ModelError("the local server returned an unexpected shape")
        return data

    def prepare(self) -> dict[str, Any]:
        """Check that the model is installed and record its identity."""
        models = self._request("/api/tags").get("models")
        if not isinstance(models, list):
            raise ModelError("unexpected /api/tags response")
        self.model_info = next((entry for entry in models if isinstance(entry, dict) and entry.get("name") == self.model), None)
        if self.model_info is None:
            raise ModelError(f"model not installed locally: {self.model}")
        version = self._request("/api/version").get("version")
        if not isinstance(version, str):
            raise ModelError("could not read the Ollama version")
        self.runtime_version = version
        return self.identity()

    def identity(self) -> dict[str, Any]:
        info = self.model_info or {}
        details = info.get("details") if isinstance(info.get("details"), dict) else {}
        return {"model": self.model, "digest": info.get("digest"), "ollama_version": self.runtime_version,
                "quantization": details.get("quantization_level"), "parameter_size": details.get("parameter_size"),
                "options": dict(self.options), "think": self.think, "flags": dict(CHAT_FLAGS)}

    def chat(self, messages: Sequence[dict[str, Any]], *, tools: list[dict[str, Any]] | None = None,
             schema: dict[str, Any] | None = None) -> Reply:
        self.last_exchange = None
        if self.model_info is None:
            self.prepare()
        payload: dict[str, Any] = {"model": self.model, "messages": copy.deepcopy(list(messages)), "stream": False,
                                   "options": dict(self.options), **CHAT_FLAGS}
        if tools:
            payload["tools"] = copy.deepcopy(tools)
        if schema is not None:
            payload["format"] = copy.deepcopy(schema)
        if self.think is not None:
            payload["think"] = self.think
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")  # exactly the bytes _request sends
        exchange: dict[str, Any] = {"request": copy.deepcopy(payload), "request_sha256": hashlib.sha256(encoded).hexdigest(),
                                    "response": None, "error": None, "elapsed_ms": None}
        self.last_exchange = exchange
        started = self.clock()
        self.attempts += 1
        try:
            response = self._request("/api/chat", payload)
        except ModelError as exc:
            exchange.update(error=str(exc), elapsed_ms=round((self.clock() - started) * 1000, 1))
            raise
        elapsed_ms = round((self.clock() - started) * 1000, 1)
        exchange.update(response=copy.deepcopy(response), elapsed_ms=elapsed_ms)
        message = response.get("message")
        if response.get("done") is not True or not isinstance(message, dict) or not isinstance(message.get("content"), str):
            exchange["error"] = f"incomplete chat response (done={response.get('done')!r})"
            raise ModelError(exchange["error"])
        calls = message.get("tool_calls") or []
        if not isinstance(calls, list):
            exchange["error"] = "tool_calls is not a list"
            raise ModelError(exchange["error"])
        self.responses += 1
        # malformed entries are kept as they are; the runner answers each one with an error
        return Reply(message["content"], list(calls), message.get("thinking"), {
            "elapsed_ms": elapsed_ms, "done_reason": response.get("done_reason"),
            "prompt_tokens": response.get("prompt_eval_count"), "output_tokens": response.get("eval_count"),
            "total_duration_ns": response.get("total_duration"), "load_duration_ns": response.get("load_duration")})


class ScriptedChat:
    """Plays back prepared replies; used by tests and by the rules-only dry runs."""

    def __init__(self, script: Callable[[Sequence[dict[str, Any]], Any, Any], Reply] | Sequence[Reply]):
        self.script = script if callable(script) else iter(list(script))
        self.attempts = 0
        self.responses = 0
        self.calls: list[dict[str, Any]] = []
        self.last_exchange: dict[str, Any] | None = None

    def identity(self) -> dict[str, Any]:
        return {"model": "scripted", "digest": None}

    def chat(self, messages, *, tools=None, schema=None) -> Reply:
        self.attempts += 1
        request = {"messages": copy.deepcopy(list(messages)), "tools": bool(tools), "schema": schema is not None}
        self.calls.append(request)
        self.last_exchange = {"request": request, "request_sha256": None, "response": None, "error": None, "elapsed_ms": None}
        try:
            reply = self.script(messages, tools, schema) if callable(self.script) else next(self.script)
        except StopIteration:
            self.last_exchange["error"] = "the script has no more replies"
            raise ModelError(self.last_exchange["error"]) from None
        except ModelError as exc:
            self.last_exchange["error"] = str(exc)
            raise
        self.responses += 1
        self.last_exchange["response"] = {"content": reply.content, "tool_calls": reply.tool_calls}
        return reply
