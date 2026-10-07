"""Run the development questions in one of three modes and score them (docs/EVAL_DESIGN.ko.md).

    python eval/run_eval.py --mode rules                                  # ① no model
    python eval/run_eval.py --mode oracle --model gpt-oss:20b --out runs/x # ② needs a local Ollama
    python eval/run_eval.py --mode full --model gpt-oss:20b --out runs/y   # ③

Runs offline from the response cache and never needs the OpenDART key. Each
question runs once; nothing is retried or re-sampled.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from dart_review.agent import MAX_MODEL_CALLS as AGENT_MAX_MODEL_CALLS, MAX_TOOL_CALLS as AGENT_MAX_TOOL_CALLS  # noqa: E402
from dart_review.agent import DECISION_SCHEMA, agent_turn, tool_phase  # noqa: E402
from dart_review.answer import ANSWER_SCHEMA  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS  # noqa: E402
from dart_review.llm import ModelError, OllamaChat  # noqa: E402
from dart_review.prompts import (  # noqa: E402
    AGENT_PROMPT_VERSION, AGENT_SYSTEM_PROMPT, DECISION_INSTRUCTION, FINAL_INSTRUCTION, PROMPT_VERSION, SYSTEM_PROMPT,
    oracle_message,
)
from dart_review.render import clarification_answer, structured_answer  # noqa: E402
from dart_review.tools import TOOL_SPECS, ToolArgumentError, execute_tool, find_company  # noqa: E402
from finalize import write_review_files  # noqa: E402
from scoring import CaseScore, score_case, summarize  # noqa: E402

SPEC = ROOT / "eval" / "dev_questions.json"
GOLD = ROOT / "eval" / "dev_gold.json"
CACHE = ROOT / "cache"
MODES = ("rules", "oracle", "full", "agent")
MAX_MODEL_CALLS = AGENT_MAX_MODEL_CALLS  # per question in the full flow and agent modes, including the final request
MAX_TOOL_CALLS = AGENT_MAX_TOOL_CALLS


def interpretation_calls(question: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls the correct reading of the question makes (from the hand-written expectations)."""
    expected = question["expected"]
    company = DEV_COMPANIES[expected["corp_code"]]
    if expected["action"] == "side_by_side":
        return [("side_by_side", {"company": company, "account": expected["account"], "period": expected["period"]})]
    accounts = expected["options"] if expected["action"] == "clarify" else [expected["account"]]
    return [("compare_values", {"company": company, "basis": FS_DIVS[expected["fs_div"]], "account": account,
                                "current_period": expected["current"], "base_period": expected["base"]})
            for account in accounts]


def rules_answer(question: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mode ①: the product's own renderer on the tool results of the correct reading."""
    expected = question["expected"]
    if expected["action"] == "clarify":
        return clarification_answer(DEV_COMPANIES[expected["corp_code"]], [result["account"] for result in results])
    return structured_answer(results[0])


def _same_call(call: tuple[Any, Any], expected: tuple[str, dict[str, Any]]) -> bool:
    name, arguments = call
    if isinstance(arguments, str):  # Ollama may pass arguments as a JSON string
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return False
    if name != expected[0] or not isinstance(arguments, dict) or set(arguments) != set(expected[1]):
        return False
    for key, value in expected[1].items():
        if key == "company":
            try:
                if find_company(arguments[key]) != find_company(value):
                    return False
            except ToolArgumentError:
                return False
        elif arguments[key] != value:
            return False
    return True


def run_case(mode: str, question: dict[str, Any], gold: dict[str, Any], client: DartClient, chat: Any = None,
             clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Run one question. Model failures, evaluator bugs, and budget overruns fail only this question."""
    started = clock()
    record: dict[str, Any] = {"id": question["id"], "mode": mode, "question": question["question"], "requests": [],
                              "replies": [], "tool_calls": [], "model_attempts": 0, "model_responses": 0,
                              "model_latency_ms": 0.0, "tool_call_count": 0, "budget_exceeded": False,
                              "tool_args_first_ok": None, "tool_args_any_ok": None, "model_error": None,
                              "evaluator_error": None, "answer": None, "seen": [], "decision": None,
                              "decision_error": None, "no_result": False, "explanation_dropped": None}
    seen = record["seen"]

    def ask(messages: list[dict[str, Any]], **kwargs: Any):
        record["model_attempts"] += 1
        try:
            reply = chat.chat(messages, **kwargs)
        finally:
            # whatever happened, keep the exact request and the raw response or error
            record["requests"].append(copy.deepcopy(getattr(chat, "last_exchange", None)))
        record["model_responses"] += 1
        record["model_latency_ms"] = round(record["model_latency_ms"] + (reply.metadata.get("elapsed_ms") or 0), 1)
        record["replies"].append({"content": reply.content, "tool_calls": reply.tool_calls,
                                  "thinking": reply.thinking, "metadata": reply.metadata})
        return reply

    try:
        if mode in ("rules", "oracle"):
            for name, arguments in interpretation_calls(question):
                seen.append(execute_tool(client, name, arguments))
            if mode == "rules":
                record["answer"] = rules_answer(question, seen)
            else:
                messages = [{"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": oracle_message(question["question"], seen)}]
                record["answer"] = ask(messages, schema=ANSWER_SCHEMA).content
        elif mode == "full":
            _run_full(question, client, record, ask)
        else:  # agent: the 2-1 design (model decides, code writes the facts)
            agent_turn(question["question"], client, record, ask)
    except ModelError as exc:
        record["model_error"] = str(exc)
    except Exception as exc:  # a bug in the evaluator, not a model mistake: recorded and reported, never hidden
        record["evaluator_error"] = f"{type(exc).__name__}: {exc}"
        record["evaluator_traceback"] = traceback.format_exc(limit=8)
    if mode in ("full", "agent") and not record["evaluator_error"]:
        try:  # also after a model error or an overrun: the calls made so far still count
            tool_argument_metrics(question, record)
        except Exception as exc:
            record["evaluator_error"] = f"{type(exc).__name__} in tool metrics: {exc}"
            record["evaluator_traceback"] = traceback.format_exc(limit=8)
    try:
        score = score_case(gold, record["answer"], seen, question["question"])
    except Exception as exc:
        record["evaluator_error"] = record["evaluator_error"] or f"{type(exc).__name__} while scoring: {exc}"
        record["evaluator_traceback"] = traceback.format_exc(limit=8)
        score = CaseScore(question["id"], format_error="evaluator error")
    if record["model_error"]:
        score.format_error = f"model error: {record['model_error']}"
    elif record["evaluator_error"]:
        score.format_error = "evaluator error"
    elif record["budget_exceeded"]:
        score.format_error = "budget exceeded (no final answer)"
    elif record["decision_error"]:
        score.format_error = f"decision format error: {record['decision_error']}"
    elif record["no_result"]:
        score.format_error = "no successful tool result to answer from"
    if record["model_error"] or record["evaluator_error"] or record["budget_exceeded"]:
        score.automatic_passed = False
    record["score"] = score.to_dict()
    record["wall_ms"] = round((clock() - started) * 1000, 1)
    return record


def _run_full(question: dict[str, Any], client: DartClient, record: dict[str, Any], ask: Callable[..., Any]) -> None:
    """Mode ③ (1-4 design): the model calls tools, then writes the whole answer JSON itself."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question["question"]}]
    if tool_phase(messages, client, record, ask, max_model_calls=MAX_MODEL_CALLS, max_tool_calls=MAX_TOOL_CALLS):
        messages.append({"role": "user", "content": FINAL_INSTRUCTION})
        record["answer"] = ask(messages, schema=ANSWER_SCHEMA).content


def tool_argument_metrics(question: dict[str, Any], record: dict[str, Any]) -> None:
    """First tool call matches the correct reading; some successful call does (after recovery)."""
    if question["expected"]["action"] == "clarify":
        return
    expected = interpretation_calls(question)[0]
    calls = record["tool_calls"]
    record["tool_args_first_ok"] = bool(calls) and _same_call((calls[0]["name"], calls[0]["arguments"]), expected)
    record["tool_args_any_ok"] = any(_same_call((call["name"], call["arguments"]), expected) and "error" not in call["result"]
                                     for call in calls)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def contract_hashes() -> dict[str, str]:
    """Fingerprints of everything that defines the evaluation, recorded with each run."""
    def text(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"gold": _sha256(GOLD.read_bytes()), "questions": _sha256(SPEC.read_bytes()),
            "system_prompt": _sha256(SYSTEM_PROMPT.encode("utf-8")), "final_instruction": _sha256(FINAL_INSTRUCTION.encode("utf-8")),
            "tools": _sha256(text(TOOL_SPECS)), "answer_schema": _sha256(text(ANSWER_SCHEMA)),
            "agent_prompt": _sha256(AGENT_SYSTEM_PROMPT.encode("utf-8")), "decision_instruction": _sha256(DECISION_INSTRUCTION.encode("utf-8")),
            "decision_schema": _sha256(text(DECISION_SCHEMA))}


def run(mode: str, chat: Any, client: DartClient, only: list[str] | None = None,
        on_case: Callable[[dict[str, Any]], None] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    gold = {answer["id"]: answer for answer in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    questions = [question for question in spec["questions"] if not only or question["id"] in only]
    cases = []
    for question in questions:
        case = run_case(mode, question, gold[question["id"]], client, chat)
        cases.append(case)
        if on_case:
            on_case(case)
    return cases, summarize(cases)


def no_key() -> str:
    raise RuntimeError("evaluation runs must not need the OpenDART key; fetch the cache first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--model", help="local Ollama model name (oracle and full modes)")
    parser.add_argument("--only", nargs="+", help="question ids to run")
    parser.add_argument("--out", type=Path, help="new directory for run.json, cases.jsonl, summary.json, review files")
    parser.add_argument("--allow-dirty", action="store_true", help="allow a model run with uncommitted changes")
    args = parser.parse_args(argv)
    if (args.mode == "rules") == bool(args.model):
        parser.error("--model is required for oracle and full, and not used for rules")
    if args.model and not args.out:
        parser.error("model runs must be recorded: pass --out")
    if args.out and args.out.exists():
        parser.error(f"{args.out} exists; results are never overwritten")
    git = _git_state()
    if args.model and git["dirty"] and not args.allow_dirty:
        parser.error("commit first: a model run must name the exact code it ran (or pass --allow-dirty)")
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
    chat = OllamaChat(args.model) if args.model else None
    identity = chat.prepare() if chat else None
    handle = None
    if args.out:
        # written as the run goes, so an interrupted run keeps every finished question
        args.out.mkdir(parents=True)
        meta = {"mode": args.mode, "model": identity, "contract": contract_hashes(),
                "prompt_version": AGENT_PROMPT_VERSION if args.mode == "agent" else PROMPT_VERSION,
                "git": git, "budget": {"model_calls": MAX_MODEL_CALLS, "tool_calls": MAX_TOOL_CALLS},
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        (args.out / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        handle = (args.out / "cases.jsonl").open("w", encoding="utf-8")

    def save(case: dict[str, Any]) -> None:
        if handle:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
            handle.flush()

    try:
        cases, summary = run(args.mode, chat, client, args.only, on_case=save)
    finally:
        if handle:
            handle.close()
    summary["network_requests"] = client.network_requests
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        write_review_files(args.out, cases)
    return 1 if summary["evaluator_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
