"""The agent: the model reads the question and calls tools; code writes the facts (roadmap 2-1).

Flow for one question:
1. Tool phase: the model calls compare_values / side_by_side until it stops
   (budget: 5 model requests including the decision, 3 tool calls; over
   budget the question ends with no answer and no request carrying an
   unanswered tool call).
2. Decision: one structured request with only {action, clarify_accounts,
   explanation}. The model never writes the factual sentences.
3. Answer: code renders the facts from the last successful tool result
   (dart_review/render.py). The model's explanation is shown only if every
   number in it is grounded in a successful tool result or the question's
   years; otherwise it is dropped and the drop is recorded.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Callable

from .accounts import ACCOUNTS
from .client import DartClient
from .companies import DEV_COMPANIES
from .numbers import allowed_from, check_text, question_years, ungrounded
from .prompts import AGENT_SYSTEM_PROMPT, DECISION_INSTRUCTION
from .render import clarification_answer, structured_answer
from .tools import TOOL_SPECS, execute_tool

MAX_MODEL_CALLS = 5  # including the decision request
MAX_TOOL_CALLS = 3
MAX_EXPLANATION_CHARS = 300

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["answer", "clarify"]},
        "clarify_accounts": {"type": "array", "items": {"type": "string", "enum": list(ACCOUNTS)}},
        "explanation": {"type": ["string", "null"]},
    },
    "required": ["action", "clarify_accounts", "explanation"],
    "additionalProperties": False,
}


class DecisionError(ValueError):
    pass


def parse_decision(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except ValueError:
        raise DecisionError("the decision is not JSON") from None
    if not isinstance(data, dict) or set(data) != {"action", "clarify_accounts", "explanation"}:
        raise DecisionError("the decision must have exactly action, clarify_accounts, explanation")
    if data["action"] not in ("answer", "clarify"):
        raise DecisionError(f"unknown action {data['action']!r}")
    accounts = data["clarify_accounts"]
    if not isinstance(accounts, list) or not all(isinstance(key, str) and key in ACCOUNTS for key in accounts):
        raise DecisionError("clarify_accounts must list account keys")
    if data["explanation"] is not None and not isinstance(data["explanation"], str):
        raise DecisionError("explanation must be a string or null")
    return data


def tool_phase(messages: list[dict[str, Any]], client: DartClient, record: dict[str, Any], ask: Callable[..., Any],
               *, max_model_calls: int = MAX_MODEL_CALLS, max_tool_calls: int = MAX_TOOL_CALLS) -> bool:
    """Let the model call tools; True when it stopped within budget (the last request is left for the final one)."""
    while True:
        if record["model_attempts"] >= max_model_calls - 1:
            record["budget_exceeded"] = True
            return False
        reply = ask(messages, tools=TOOL_SPECS)
        if not reply.tool_calls:
            messages.append(reply.message())
            return True
        if record["tool_call_count"] + len(reply.tool_calls) > max_tool_calls:
            record["budget_exceeded"] = True
            record["unexecuted_tool_calls"] = copy.deepcopy(reply.tool_calls)
            return False
        messages.append(reply.message())
        for call in reply.tool_calls:
            function = call.get("function") if isinstance(call, dict) and isinstance(call.get("function"), dict) else {}
            name, arguments = function.get("name"), function.get("arguments")
            result = execute_tool(client, name, arguments) if function else {"error": "도구 호출 형식이 맞지 않는다"}
            record["tool_call_count"] += 1
            record["tool_calls"].append({"raw": copy.deepcopy(call), "name": name, "arguments": arguments, "result": result})
            record["seen"].append(result)
            messages.append({"role": "tool", "tool_name": name if isinstance(name, str) else "",
                             "content": json.dumps(result, ensure_ascii=False)})


def company_in(question: str) -> str:
    """The company a question names (for a clarification asked before any tool call)."""
    compact = question.replace(" ", "")
    return next((name for name in DEV_COMPANIES.values() if name.replace(" ", "") in compact), "")


def check_explanation(text: str | None, seen: list[Any], question: str) -> tuple[str | None, str | None]:
    """(text to show, reason it was dropped)."""
    if text is None or not text.strip():
        return None, None
    if len(text) > MAX_EXPLANATION_CHARS:
        return None, f"longer than {MAX_EXPLANATION_CHARS} characters"
    allowed = allowed_from(*seen)
    allowed.years |= question_years(question)
    bad = [mention.text for mention in ungrounded(check_text(text, allowed))]
    if bad:
        return None, f"ungrounded numbers {bad}"
    return text.strip(), None


def agent_turn(question: str, client: DartClient, record: dict[str, Any], ask: Callable[..., Any]) -> None:
    """Run the agent on one question, filling ``record`` (answer is None when there is nothing to report)."""
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}, {"role": "user", "content": question}]
    if not tool_phase(messages, client, record, ask):
        return
    messages.append({"role": "user", "content": DECISION_INSTRUCTION})
    reply = ask(messages, schema=DECISION_SCHEMA)
    try:
        decision = parse_decision(reply.content)
    except DecisionError as exc:
        record["decision_error"] = str(exc)
        return
    record["decision"] = decision
    successful = [result for result in record["seen"] if isinstance(result, dict) and "error" not in result]
    if decision["action"] == "clarify":
        company = successful[-1]["company"] if successful else company_in(question)
        record["answer"] = clarification_answer(company, decision["clarify_accounts"])
        return
    if not successful:
        record["no_result"] = True
        return
    explanation, dropped = check_explanation(decision["explanation"], record["seen"], question)
    if dropped:
        record["explanation_dropped"] = dropped
    record["answer"] = structured_answer(successful[-1], explanation)
