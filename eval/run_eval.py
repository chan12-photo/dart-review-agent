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

from dart_review.answer import ANSWER_SCHEMA  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS  # noqa: E402
from dart_review.llm import ModelError, OllamaChat  # noqa: E402
from dart_review.prompts import FINAL_INSTRUCTION, PROMPT_VERSION, SYSTEM_PROMPT, oracle_message  # noqa: E402
from dart_review.tools import TOOL_SPECS, ToolArgumentError, execute_tool, find_company  # noqa: E402
from finalize import write_review_files  # noqa: E402
from scoring import CaseScore, score_case, summarize  # noqa: E402

SPEC = ROOT / "eval" / "dev_questions.json"
GOLD = ROOT / "eval" / "dev_gold.json"
CACHE = ROOT / "cache"
MODES = ("rules", "oracle", "full")
MAX_MODEL_CALLS = 5  # per question in the full flow, including the final answer
MAX_TOOL_CALLS = 3


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


def _value(fact: dict[str, Any]) -> dict[str, Any]:
    return {"basis": fact["basis"], "start": fact["period"]["start"], "end": fact["period"]["end"], "amount": fact["amount"]}


def rules_answer(question: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    """Mode ①: a fixed-template answer straight from the tool results."""
    expected = question["expected"]
    company = DEV_COMPANIES[expected["corp_code"]]
    if expected["action"] == "clarify":
        labels = " 또는 ".join(result["account_label"] for result in results)
        ask = f"질문의 '이익'이 {labels} 중 어느 것인지 알려 주세요."
        return {"status": "되묻기", "company": company, "account": None, "values": [], "change": None,
                "change_pct": None, "answer": ask, "clarifying_question": ask}
    result = results[0]
    if result["tool"] == "side_by_side":
        cfs, ofs = result["values"]
        bigger = "크다" if result["difference"] >= 0 else "작다"
        text = (f"{company} {result['account_label']} ({result['period']['label']}): 연결 {cfs['amount']:,}원, "
                f"별도 {ofs['amount']:,}원. 연결이 별도보다 {abs(result['difference']):,}원 {bigger}. "
                "같은 시점의 집계 범위 차이이며 시간에 따른 변화가 아니다.")
        return {"status": "나란히 표시", "company": company, "account": result["account"],
                "values": [_value(cfs), _value(ofs)], "change": None, "change_pct": None, "answer": text,
                "clarifying_question": None}
    status = result["status"]
    if status in ("비교 가능", "확인 필요"):
        current, base = result["current"], result["base"]
        rate = f"{result['change_pct']}%, " if result["change_pct"] is not None else ""
        text = (f"{company} {result['basis']} 기준 {result['account_label']}: {current['period']['label']} {current['amount']:,}원, "
                f"{base['period']['label']} {base['amount']:,}원. 변화 {result['change']:,}원 ({rate}{result['direction']}).")
        if status == "확인 필요":
            text = "확인 필요: " + " / ".join(result["reasons"]) + "\n" + text
        return {"status": status, "company": company, "account": result["account"],
                "values": [_value(current), _value(base)], "change": result["change"],
                "change_pct": result["change_pct"], "answer": text, "clarifying_question": None}
    return {"status": status, "company": company, "account": result["account"], "values": [], "change": None,
            "change_pct": None, "answer": f"{status}: " + " / ".join(result["reasons"]), "clarifying_question": None}


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
                              "evaluator_error": None, "answer": None, "seen": []}
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
        else:
            _run_full(question, client, record, ask)
    except ModelError as exc:
        record["model_error"] = str(exc)
    except Exception as exc:  # a bug in the evaluator, not a model mistake: recorded and reported, never hidden
        record["evaluator_error"] = f"{type(exc).__name__}: {exc}"
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
    if record["model_error"] or record["evaluator_error"] or record["budget_exceeded"]:
        score.automatic_passed = False
    record["score"] = score.to_dict()
    record["wall_ms"] = round((clock() - started) * 1000, 1)
    return record


def _run_full(question: dict[str, Any], client: DartClient, record: dict[str, Any], ask: Callable[..., Any]) -> None:
    """Mode ③: tool calls until the model stops calling tools, then one structured final answer.

    Over budget (model requests or tool calls), the question ends there without a final request, so no
    tool call is ever left without its result in the conversation.
    """
    seen = record["seen"]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question["question"]}]
    expected = interpretation_calls(question)[0] if question["expected"]["action"] != "clarify" else None
    if expected:
        record["tool_args_first_ok"] = record["tool_args_any_ok"] = False
    while True:
        if record["model_attempts"] >= MAX_MODEL_CALLS - 1:  # the last request is reserved for the final answer
            record["budget_exceeded"] = True
            return
        reply = ask(messages, tools=TOOL_SPECS)
        if not reply.tool_calls:
            messages.append(reply.message())
            break
        if record["tool_call_count"] + len(reply.tool_calls) > MAX_TOOL_CALLS:
            record["budget_exceeded"] = True
            record["unexecuted_tool_calls"] = copy.deepcopy(reply.tool_calls)
            return
        messages.append(reply.message())
        for call in reply.tool_calls:
            function = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            name, arguments = function.get("name"), function.get("arguments")
            result = execute_tool(client, name, arguments) if function else {"error": "도구 호출 형식이 맞지 않는다"}
            first = record["tool_call_count"] == 0
            record["tool_call_count"] += 1
            record["tool_calls"].append({"raw": copy.deepcopy(call), "name": name, "arguments": arguments, "result": result})
            if expected:
                matched = _same_call((name, arguments), expected)
                if first:
                    record["tool_args_first_ok"] = matched
                record["tool_args_any_ok"] = record["tool_args_any_ok"] or (matched and "error" not in result)
            seen.append(result)
            messages.append({"role": "tool", "tool_name": name if isinstance(name, str) else "",
                             "content": json.dumps(result, ensure_ascii=False)})
    messages.append({"role": "user", "content": FINAL_INSTRUCTION})
    record["answer"] = ask(messages, schema=ANSWER_SCHEMA).content


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
            "tools": _sha256(text(TOOL_SPECS)), "answer_schema": _sha256(text(ANSWER_SCHEMA))}


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
        meta = {"mode": args.mode, "model": identity, "prompt_version": PROMPT_VERSION, "contract": contract_hashes(),
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
