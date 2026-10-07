"""The local model adapter (fake HTTP, no Ollama needed), the answer format, and tool argument checks."""

import io
import json
from pathlib import Path
import unittest
import urllib.error

from dart_review.answer import ANSWER_SCHEMA, AnswerFormatError, parse_answer
from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.llm import BASE_URL, ModelError, OllamaChat, Reply
from dart_review.tools import TOOL_SPECS, execute_tool, find_company, parse_period, ToolArgumentError

ROOT = Path(__file__).resolve().parents[1]
TAGS = {"models": [{"name": "gpt-oss:20b", "digest": "abc123", "details": {"quantization_level": "MXFP4", "parameter_size": "20.9B"}}]}


class FakeResponse:
    def __init__(self, body, url):
        self.body, self.url = json.dumps(body).encode("utf-8"), url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit):
        return self.body[:limit]


class FakeOpener:
    def __init__(self, chat_reply=None, redirect_to=None, error=None):
        self.requests, self.chat_reply, self.redirect_to, self.error = [], chat_reply, redirect_to, error

    def open(self, request, timeout):
        self.requests.append(request)
        path = request.full_url[len(BASE_URL):]
        if path == "/api/chat" and self.error:
            raise self.error
        body = {"/api/tags": TAGS, "/api/version": {"version": "0.34.4"}}.get(path, self.chat_reply)
        return FakeResponse(body, self.redirect_to or request.full_url)


CHAT_REPLY = {"done": True, "done_reason": "stop", "message": {"role": "assistant", "content": "{}", "thinking": "생각",
              "tool_calls": [{"function": {"name": "compare_values", "arguments": {}}}]},
              "prompt_eval_count": 120, "eval_count": 30, "total_duration": 5, "load_duration": 1}


class OllamaChatTests(unittest.TestCase):
    def test_payload_and_metadata(self):
        opener = FakeOpener(CHAT_REPLY)
        ticks = iter([10.0, 10.25])
        chat = OllamaChat("gpt-oss:20b", opener=opener, clock=lambda: next(ticks))
        reply = chat.chat([{"role": "user", "content": "질문"}], tools=TOOL_SPECS, schema=ANSWER_SCHEMA)
        payload = json.loads(opener.requests[-1].data)
        self.assertTrue(all(request.full_url.startswith("http://127.0.0.1:11434/") for request in opener.requests))
        self.assertEqual((payload["truncate"], payload["shift"], payload["stream"]), (False, False, False))
        self.assertEqual(payload["format"], ANSWER_SCHEMA)
        self.assertEqual(payload["tools"], TOOL_SPECS)
        self.assertNotIn("think", payload)
        self.assertEqual(payload["options"]["temperature"], 0)
        self.assertEqual((reply.thinking, reply.metadata["elapsed_ms"], reply.metadata["prompt_tokens"]), ("생각", 250.0, 120))
        self.assertEqual(chat.identity()["digest"], "abc123")
        self.assertEqual(reply.message()["tool_calls"], CHAT_REPLY["message"]["tool_calls"])

    def test_missing_model_redirect_and_http_errors(self):
        with self.assertRaises(ModelError):
            OllamaChat("qwen3:4b", opener=FakeOpener(CHAT_REPLY)).prepare()
        with self.assertRaises(ModelError):
            OllamaChat("gpt-oss:20b", opener=FakeOpener(CHAT_REPLY, redirect_to="http://example.com/x")).prepare()
        error = urllib.error.HTTPError(BASE_URL + "/api/chat", 400, "bad", {}, io.BytesIO(b'{"error":"exceeds context"}'))
        with self.assertRaises(ModelError) as caught:
            OllamaChat("gpt-oss:20b", opener=FakeOpener(CHAT_REPLY, error=error)).chat([])
        self.assertIn("exceeds context", str(caught.exception))
        with self.assertRaises(ModelError):
            OllamaChat("gpt-oss:20b", opener=FakeOpener({"done": False, "message": {"content": ""}})).chat([])

    def test_think_is_sent_only_when_set(self):
        opener = FakeOpener(CHAT_REPLY)
        OllamaChat("gpt-oss:20b", opener=opener, think="low").chat([])
        self.assertEqual(json.loads(opener.requests[-1].data)["think"], "low")


VALID = {"status": "비교 가능", "company": "삼성전자", "account": "revenue",
         "values": [{"basis": "연결", "start": "2025-01-01", "end": "2025-12-31", "amount": 1}],
         "change": 1, "change_pct": "10.00", "answer": "답", "clarifying_question": None}


class AnswerFormatTests(unittest.TestCase):
    def test_valid_answer(self):
        answer = parse_answer(json.dumps(VALID, ensure_ascii=False))
        self.assertEqual((answer.decision, answer.values[0].amount), ("answer", 1))
        self.assertEqual(Reply("x").message(), {"role": "assistant", "content": "x"})

    def test_every_deviation_is_a_format_error(self):
        broken = [
            {**VALID, "extra": 1}, {k: v for k, v in VALID.items() if k != "answer"}, {**VALID, "status": "OK"},
            {**VALID, "account": "profit"}, {**VALID, "change": 1.5}, {**VALID, "change": True}, {**VALID, "change_pct": "10.9"},
            {**VALID, "change_pct": 10.0}, {**VALID, "answer": " "},
            {**VALID, "values": [{**VALID["values"][0], "amount": 1.0}]},
            {**VALID, "values": [{**VALID["values"][0], "basis": "CFS"}]},
            {**VALID, "values": [{**VALID["values"][0], "end": "2025-13-01"}]},
            {**VALID, "values": [{**VALID["values"][0], "note": "x"}]},
        ]
        for data in broken:
            with self.subTest(data=data):
                with self.assertRaises(AnswerFormatError):
                    parse_answer(json.dumps(data, ensure_ascii=False))
        with self.assertRaises(AnswerFormatError):
            parse_answer("```json\n{}\n```")


class ToolArgumentTests(unittest.TestCase):
    def test_company_and_period_checks(self):
        self.assertEqual(find_company(" 삼성 전자"), "00126380")
        for name in ("LG에너지솔루션", "CJ 제일제당", "현대자동차", "", None):
            with self.subTest(name=name):
                with self.assertRaises(ToolArgumentError):
                    find_company(name)
        for spec in ({"kind": "quarter", "year": 2025, "month": 8}, {"kind": "half", "year": 2025, "month": 6},
                     {"kind": "quarter", "year": "2025", "month": 9}, {"kind": "quarter", "year": 2025}):
            with self.subTest(spec=spec):
                with self.assertRaises(ToolArgumentError):
                    parse_period(spec, "period")

    def test_bad_calls_become_error_results(self):
        client = DartClient(ResponseCache(ROOT / "nonexistent-cache"), key_loader=lambda: (_ for _ in ()).throw(AssertionError()), offline=True)
        self.assertIn("error", execute_tool(client, "delete_everything", {}))
        self.assertIn("error", execute_tool(client, "compare_values", "not json"))
        self.assertIn("error", execute_tool(client, "compare_values", {"company": "삼성전자"}))
        arguments = {"company": "삼성전자", "basis": "연결", "account": "revenue",
                     "current_period": {"kind": "year_to_date", "year": 2025, "month": 12},
                     "base_period": {"kind": "year_to_date", "year": 2024, "month": 12}}
        result = execute_tool(client, "compare_values", json.dumps(arguments, ensure_ascii=False))
        self.assertIn("캐시에 없다", result["error"])
        self.assertEqual(client.network_requests, 0)


if __name__ == "__main__":
    unittest.main()
