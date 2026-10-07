"""Replay demo (roadmap 2-4): the representative requests answered with no key, no model server, no network.

Recorded inputs, committed under demo/:
- demo/opendart/: OpenDART responses in the response-cache layout, trimmed to
  the rows of the six target accounts (see demo/README.md);
- demo/model_replies.json: the model's recorded reading for each question,
  with the SHA-256 of the exact messages it was given.

The replay runs the real cross-check code (rules, comparison, rendering,
output check). Only the model is replaced, and the replay stops if the
messages built now differ from the recorded ones (a prompt or question
change), so the demo cannot silently drift from what was recorded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .cache import ResponseCache
from .client import DartClient
from .crosscheck import crosscheck_turn
from .llm import ModelError, Reply
from .render import markdown_report

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo"
# SCOPE section 2: the five representative requests (development questions dev01, dev02, dev03, dev05, dev11)
DEMO_QUESTIONS = [
    "삼성전자 2025년 매출액이 전년보다 얼마나 늘었어?",
    "삼성전자 2025년 3분기말 자산총계를 작년 3분기말과 비교해 줘.",
    "삼성전자의 2025년 3분기까지 누적 영업활동현금흐름은 얼마이고, 작년 같은 기간보다 얼마나 늘었어?",
    "삼성전자 2025년 연결 매출이랑 별도 매출은 각각 얼마야? 차이가 왜 이렇게 커?",
    "삼성전자 2014년 매출액을 2013년과 비교해 줘.",
]


class ReplayMismatch(ModelError):
    pass


def messages_sha256(messages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


class ReplayChat:
    """Serves the recorded model reading for a question, after checking the request is unchanged."""

    def __init__(self, replies: dict[str, dict[str, str]]):
        self.replies = replies
        self.attempts = 0
        self.last_exchange: dict[str, Any] | None = None

    def chat(self, messages, *, tools=None, schema=None) -> Reply:
        self.attempts += 1
        question = messages[-1]["content"]
        recorded = self.replies.get(question)
        if recorded is None:
            raise ReplayMismatch(f"no recorded reply for: {question}")
        if messages_sha256(messages) != recorded["messages_sha256"]:
            raise ReplayMismatch("the messages differ from the recording (prompt or question changed)")
        self.last_exchange = {"request": {"messages": messages}, "response": {"content": recorded["content"]}, "error": None}
        return Reply(recorded["content"])


def new_record() -> dict[str, Any]:
    return {"requests": [], "replies": [], "tool_calls": [], "model_attempts": 0, "model_responses": 0,
            "tool_call_count": 0, "seen": [], "no_result": False}


def answer(question: str, client: DartClient, chat: Any) -> dict[str, Any]:
    """One cross-checked answer, as the demo and the CLI show it."""
    record = new_record()

    def ask(messages, **kwargs):
        record["model_attempts"] += 1
        reply = chat.chat(messages, **kwargs)
        record["model_responses"] += 1
        return reply

    crosscheck_turn(question, client, record, ask)
    result = record["seen"][-1] if record["seen"] else None
    report = markdown_report(record["answer"], result) if record["answer"] else None
    return {"question": question, "answer": record["answer"], "report": report, "readings": record.get("readings"),
            "withheld": record.get("output_blocked"), "no_result": record["no_result"], "seen": record["seen"]}


def run_demo(demo_dir: Path = DEMO_DIR) -> tuple[list[dict[str, Any]], DartClient]:
    def no_key() -> str:
        raise RuntimeError("the demo never needs the OpenDART key")

    client = DartClient(ResponseCache(demo_dir / "opendart"), key_loader=no_key, offline=True)
    replies = json.loads((demo_dir / "model_replies.json").read_text(encoding="utf-8"))["replies"]
    chat = ReplayChat(replies)
    return [answer(question, client, chat) for question in DEMO_QUESTIONS], client
