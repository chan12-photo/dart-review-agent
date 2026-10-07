"""Run the development questions in one of three modes and score them (docs/EVAL_DESIGN.ko.md).

    python eval/run_eval.py --mode rules                                  # ① no model
    python eval/run_eval.py --mode oracle --model gpt-oss:20b --out runs/x # ② needs a local Ollama
    python eval/run_eval.py --mode full --model gpt-oss:20b --out runs/y   # ③

Runs offline from the response cache and never needs the OpenDART key. Each
question runs once; nothing is retried or re-sampled.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from dart_review.answer import ANSWER_SCHEMA  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import DEV_COMPANIES, FS_DIVS  # noqa: E402
from dart_review.llm import ModelError, OllamaChat  # noqa: E402
from dart_review.prompts import FINAL_INSTRUCTION, PROMPT_VERSION, SYSTEM_PROMPT, oracle_message  # noqa: E402
from dart_review.tools import TOOL_SPECS, ToolArgumentError, execute_tool, find_company  # noqa: E402
from scoring import score_case, summarize  # noqa: E402

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


def _same_call(call: tuple[str, dict[str, Any]], expected: tuple[str, dict[str, Any]]) -> bool:
    name, arguments = call
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


def run_case(mode: str, question: dict[str, Any], gold: dict[str, Any], client: DartClient, chat: Any = None) -> dict[str, Any]:
    record: dict[str, Any] = {"id": question["id"], "mode": mode, "question": question["question"], "replies": [],
                              "tool_calls": [], "model_requests": 0, "tool_call_count": 0, "latency_ms": 0.0,
                              "budget_exceeded": False, "tool_args_ok": None, "error": None, "answer": None}
    seen: list[dict[str, Any]] = []

    def ask(messages: list[dict[str, Any]], **kwargs: Any):
        reply = chat.chat(messages, **kwargs)
        record["model_requests"] += 1
        record["latency_ms"] = round(record["latency_ms"] + reply.metadata.get("elapsed_ms", 0), 1)
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
                record["messages"] = messages
                record["answer"] = ask(messages, schema=ANSWER_SCHEMA).content
        else:
            messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question["question"]}]
            expected_calls = interpretation_calls(question) if question["expected"]["action"] != "clarify" else None
            while record["model_requests"] < MAX_MODEL_CALLS - 1:
                reply = ask(messages, tools=TOOL_SPECS)
                messages.append(reply.message())
                if not reply.tool_calls:
                    break
                for call in reply.tool_calls:
                    function = call.get("function") or {}
                    name, arguments = function.get("name"), function.get("arguments")
                    if record["tool_call_count"] >= MAX_TOOL_CALLS:
                        record["budget_exceeded"] = True
                        break
                    result = execute_tool(client, name, arguments)
                    record["tool_call_count"] += 1
                    record["tool_calls"].append({"name": name, "arguments": arguments, "result": result})
                    if record["tool_args_ok"] is None and expected_calls and "error" not in result:
                        record["tool_args_ok"] = _same_call((name, arguments), expected_calls[0])
                    seen.append(result)
                    messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
                if record["budget_exceeded"]:
                    break
            else:
                record["budget_exceeded"] = True
            if expected_calls and record["tool_args_ok"] is None:
                record["tool_args_ok"] = False  # never made a successful call
            messages.append({"role": "user", "content": FINAL_INSTRUCTION})
            record["messages"] = messages
            record["answer"] = ask(messages, schema=ANSWER_SCHEMA).content
    except ModelError as exc:
        record["error"] = f"model error: {exc}"
    record["seen"] = seen
    score = score_case(gold, record["answer"], seen, question["question"])
    if record["error"]:
        score.format_error = record["error"]  # the cause, rather than "no answer"
        score.passed = False
    if record["budget_exceeded"]:
        score.problems.append("budget exceeded")
        score.passed = False
    record["score"] = score.to_dict()
    return record


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_state() -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain"))}


def run(mode: str, chat: Any, client: DartClient, only: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    gold = {answer["id"]: answer for answer in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    questions = [question for question in spec["questions"] if not only or question["id"] in only]
    cases = [run_case(mode, question, gold[question["id"]], client, chat) for question in questions]
    return cases, summarize(cases)


def no_key() -> str:
    raise RuntimeError("evaluation runs must not need the OpenDART key; fetch the cache first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=MODES, required=True)
    parser.add_argument("--model", help="local Ollama model name (oracle and full modes)")
    parser.add_argument("--only", nargs="+", help="question ids to run")
    parser.add_argument("--out", type=Path, help="directory for run.json, cases.jsonl, summary.json")
    args = parser.parse_args(argv)
    if (args.mode == "rules") == bool(args.model):
        parser.error("--model is required for oracle and full, and not used for rules")
    if args.out and args.out.exists():
        parser.error(f"{args.out} exists; results are never overwritten")
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
    chat = OllamaChat(args.model) if args.model else None
    identity = chat.prepare() if chat else None
    cases, summary = run(args.mode, chat, client, args.only)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if args.out:
        args.out.mkdir(parents=True)
        meta = {"mode": args.mode, "model": identity, "prompt_version": PROMPT_VERSION,
                "gold_sha256": _sha256(GOLD), "questions_sha256": _sha256(SPEC), "git": _git_state(),
                "budget": {"model_calls": MAX_MODEL_CALLS, "tool_calls": MAX_TOOL_CALLS},
                "network_requests": client.network_requests}
        (args.out / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        with (args.out / "cases.jsonl").open("w", encoding="utf-8") as handle:
            for case in cases:
                handle.write(json.dumps(case, ensure_ascii=False) + "\n")
        (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
