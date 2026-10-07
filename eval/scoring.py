"""Score one answer against the gold answer (docs/EVAL_DESIGN.ko.md sections 3-5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from statistics import median
from typing import Any, Sequence

from dart_review.answer import Answer, AnswerFormatError, parse_answer
from dart_review.numbers import allowed_from, check_text


@dataclass
class CaseScore:
    id: str
    format_error: str | None = None
    status_ok: bool = False
    decision_ok: bool = False
    numbers_ok: bool | None = None   # None: the question has no numbers to match
    basis_ok: bool | None = None
    refusal_ok: bool | None = None   # None: the question is not a refusal or clarification
    wording_ok: bool | None = None   # None: no required wording (only sign changes need one)
    ungrounded: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SIGN_WORDS = ("흑자 전환", "적자 전환", "적자 축소", "적자 확대", "적자 지속")


def same_company(written: str, expected: str) -> bool:
    def normalize(name: str) -> str:
        return name.replace("(주)", "").replace("주식회사", "").replace(" ", "")
    return normalize(written) == normalize(expected)


def expected_values(gold: dict[str, Any]) -> list[tuple[str, str | None, str, int]]:
    """(basis, start, end, amount) the answer must contain, or [] when it must contain none."""
    if gold["decision"] == "side_by_side":
        return [({"CFS": "연결", "OFS": "별도"}[basis], cell["period_range"]["start"], cell["period_range"]["end"], cell["amount"])
                for basis, cell in gold["values"].items()]
    if gold["decision"] == "answer":
        return [(gold["basis"], cell["period_range"]["start"], cell["period_range"]["end"], cell["amount"])
                for role, cell in gold["values"].items() if role in ("current", "base")]
    return []


def _sorted_keys(keys) -> list[tuple]:
    """Sort (basis, start, end) keys whose start may be None (a point in time)."""
    return sorted(keys, key=lambda key: tuple("" if part is None else str(part) for part in key))


def _structured_numbers(answer: Answer, allowed) -> list[str]:
    problems = []
    for index, value in enumerate(answer.values):
        if Decimal(abs(value.amount)) not in allowed.amounts:
            problems.append(f"values[{index}].amount={value.amount}")
    if answer.change is not None and Decimal(abs(answer.change)) not in allowed.amounts:
        problems.append(f"change={answer.change}")
    if answer.change_pct is not None and abs(Decimal(answer.change_pct)) not in allowed.percents:
        problems.append(f"change_pct={answer.change_pct}")
    return problems


def score_case(gold: dict[str, Any], raw_answer: str | dict[str, Any] | None, seen: Sequence[Any],
               question: str) -> CaseScore:
    """``seen``: the tool results the model was shown in this case (they define the grounded numbers)."""
    score = CaseScore(gold["id"])
    if raw_answer is None:
        score.format_error = "no answer"
        return score
    try:
        answer = parse_answer(raw_answer)
    except AnswerFormatError as exc:
        score.format_error = str(exc)
        return score
    decision = gold["decision"]
    score.status_ok = answer.status == gold["expected_status"]
    score.decision_ok = answer.decision == decision
    if not score.status_ok:
        score.problems.append(f"status {answer.status}, expected {gold['expected_status']}")

    expected = expected_values(gold)
    if expected:
        got = {(value.basis, value.start, value.end): value.amount for value in answer.values}
        keys_ok = len(got) == len(answer.values) and set(got) == {item[:3] for item in expected}
        score.basis_ok = same_company(answer.company, gold["company"]) and answer.account == gold["account"] and keys_ok
        if not score.basis_ok:
            score.problems.append(f"basis/period/account: got {_sorted_keys(got)} for {answer.account}, "
                                  f"expected {_sorted_keys(item[:3] for item in expected)}")
        amounts_ok = all(got.get(item[:3]) == item[3] for item in expected)
        if decision == "side_by_side":
            change_ok = answer.change is None and answer.change_pct is None
        else:
            change_ok = answer.change == gold.get("change") and answer.change_pct == gold.get("change_pct")
        score.numbers_ok = amounts_ok and change_ok
        if not score.numbers_ok:
            score.problems.append(f"numbers: values {answer.to_dict()['values']}, change {answer.change}, pct {answer.change_pct}")
    elif decision == "refuse":
        score.basis_ok = same_company(answer.company, gold["company"]) and answer.account == gold["account"]
    if decision == "refuse":
        score.refusal_ok = score.status_ok and not answer.values and answer.change is None and answer.change_pct is None
    elif decision == "clarify":
        question_text = answer.clarifying_question or ""
        named = all(option["label"] in question_text for option in gold["options"])
        score.refusal_ok = (score.status_ok and named and not answer.values
                            and answer.change is None and answer.change_pct is None)
        if not named:
            score.problems.append("the clarifying question does not name every candidate")

    if gold.get("direction") in SIGN_WORDS:
        # with no rate to report, the answer must say what happened (e.g. 흑자 전환)
        score.wording_ok = gold["direction"].replace(" ", "") in answer.answer.replace(" ", "")
        if not score.wording_ok:
            score.problems.append(f"the answer does not say {gold['direction']}")

    allowed = allowed_from(*seen, question)
    checks = check_text(answer.answer + "\n" + (answer.clarifying_question or ""), allowed)
    score.ungrounded = [check.mention.text for check in checks if not check.grounded] + _structured_numbers(answer, allowed)
    score.unparsed = [check.mention.text for check in checks if check.mention.kind == "unparsed"]
    score.warnings = [term for term in gold.get("forbidden_terms", []) if term in answer.answer]

    score.passed = (score.status_ok and score.decision_ok and score.numbers_ok is not False
                    and score.basis_ok is not False and score.refusal_ok is not False
                    and score.wording_ok is not False and not score.ungrounded)
    return score


def _rate(flags: list[bool]) -> dict[str, Any]:
    return {"correct": sum(flags), "total": len(flags)}


def summarize(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate run records (each with a "score" and run counters) into the metrics of EVAL_DESIGN section 5."""
    scores = [case["score"] for case in cases]
    latencies = [case.get("latency_ms", 0) for case in cases]
    summary = {
        "cases": len(cases),
        "passed": _rate([score["passed"] for score in scores]),
        "status": _rate([score["status_ok"] for score in scores]),
        "decision": _rate([score["decision_ok"] for score in scores]),
        "numbers": _rate([score["numbers_ok"] for score in scores if score["numbers_ok"] is not None]),
        "basis": _rate([score["basis_ok"] for score in scores if score["basis_ok"] is not None]),
        "refusal_or_clarify": _rate([score["refusal_ok"] for score in scores if score["refusal_ok"] is not None]),
        "sign_wording": _rate([score["wording_ok"] for score in scores if score["wording_ok"] is not None]),
        "ungrounded_numbers": sum(len(score["ungrounded"]) for score in scores),
        "cases_with_ungrounded": sum(1 for score in scores if score["ungrounded"]),
        "unparsed_numbers": sum(len(score["unparsed"]) for score in scores),
        "format_errors": sum(1 for score in scores if score["format_error"]),
        "warnings": sum(len(score["warnings"]) for score in scores),
        "model_requests": sum(case.get("model_requests", 0) for case in cases),
        "tool_calls": sum(case.get("tool_call_count", 0) for case in cases),
        "latency_ms": {"total": round(sum(latencies), 1), "median_per_case": round(median(latencies), 1) if latencies else 0},
        "failed": [score["id"] for score in scores if not score["passed"]],
    }
    tool_args = [case["tool_args_ok"] for case in cases if case.get("tool_args_ok") is not None]
    if tool_args:
        summary["tool_args"] = _rate(tool_args)
    summary["budget_exceeded"] = sum(1 for case in cases if case.get("budget_exceeded"))
    return summary
