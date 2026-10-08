"""Score one answer against the gold answer automatically (docs/EVAL_DESIGN.ko.md sections 3-5).

The automatic score checks the structured fields, the decision, and every
number in the visible text. It does not judge whether the visible text means
the right thing (periods described correctly, the reason for a refusal, no
claims beyond the evidence); people check that against criteria fixed before
the run (eval/HUMAN_REVIEW.ko.md), and eval/finalize.py combines both.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
import json
import re
from statistics import median
from typing import Any, Sequence

from dart_review.answer import Answer, AnswerFormatError, parse_answer
from dart_review.numbers import allowed_from, check_text, extract, question_years

SIGN_WORDS = ("흑자 전환", "적자 전환", "적자 축소", "적자 확대", "적자 지속")
_NEGATED = re.compile(r"^.{0,8}?(않|아니|못)")
# names a clarifying question may use for each candidate (GOLD_RULES section 2: 순이익 = 당기순이익)
CLARIFY_NAMES = {"operating_income": ("영업이익",), "net_income": ("당기순이익", "순이익")}


@dataclass
class CaseScore:
    id: str
    format_error: str | None = None
    status_ok: bool = False
    decision_ok: bool = False
    numbers_ok: bool | None = None   # None: not applicable to this question (decided by the gold, not the answer)
    basis_ok: bool | None = None
    refusal_ok: bool | None = None
    wording_ok: bool | None = None
    ungrounded: list[str] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    automatic_passed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


def applicable(gold: dict[str, Any]) -> dict[str, bool]:
    """Which checks apply to a question; fixed by the gold so a failed answer cannot shrink a denominator."""
    return {"numbers": bool(expected_values(gold)), "basis": True,
            "refusal": gold["decision"] in ("refuse", "clarify"), "wording": gold.get("direction") in SIGN_WORDS}


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


def says(text: str, phrase: str) -> bool:
    """``phrase`` appears (spacing ignored) at least once without a negation right after it."""
    compact, target = text.replace(" ", ""), phrase.replace(" ", "")
    start = compact.find(target)
    while start != -1:
        if not _NEGATED.match(compact[start + len(target):]):
            return True
        start = compact.find(target, start + 1)
    return False


def score_case(gold: dict[str, Any], raw_answer: str | dict[str, Any] | None, seen: Sequence[Any],
               question: str) -> CaseScore:
    """``seen``: the tool results the model was shown in this case (successful ones ground numbers)."""
    score = CaseScore(gold["id"])
    applies = applicable(gold)
    answer = None
    if raw_answer is None:
        score.format_error = "no answer"
    else:
        try:
            answer = parse_answer(raw_answer)
        except AnswerFormatError as exc:
            score.format_error = str(exc)
    if answer is None:
        # every applicable check fails, so the denominators stay the same for every answer
        score.numbers_ok = False if applies["numbers"] else None
        score.basis_ok = False
        score.refusal_ok = False if applies["refusal"] else None
        score.wording_ok = False if applies["wording"] else None
        return score

    decision = gold["decision"]
    score.status_ok = answer.status == gold["expected_status"]
    score.decision_ok = answer.decision == decision
    if not score.status_ok:
        score.problems.append(f"status {answer.status}, expected {gold['expected_status']}")

    company_ok = same_company(answer.company, gold["company"])
    expected = expected_values(gold)
    if expected:
        got = {(value.basis, value.start, value.end): value.amount for value in answer.values}
        keys_ok = len(got) == len(answer.values) and set(got) == {item[:3] for item in expected}
        score.basis_ok = company_ok and answer.account == gold["account"] and keys_ok
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
        score.basis_ok = company_ok and answer.account == gold["account"]
    else:  # clarify: the right company, and no account chosen yet
        score.basis_ok = company_ok and answer.account is None
    if not score.basis_ok and not expected:
        score.problems.append(f"company/account: {answer.company}, {answer.account}")

    empty = not answer.values and answer.change is None and answer.change_pct is None
    if decision == "refuse":
        score.refusal_ok = score.status_ok and empty
    elif decision == "clarify":
        question_text = answer.clarifying_question or ""
        named = all(any(name in question_text for name in CLARIFY_NAMES.get(option["account"], (option["label"],)))
                    for option in gold["options"])
        figures = [mention.text for mention in extract(answer.answer + "\n" + question_text)
                   if mention.kind in ("amount", "percent", "point", "ratio")]
        score.refusal_ok = score.status_ok and named and empty and not figures
        if not named:
            score.problems.append("the clarifying question does not name every candidate")
        if figures:
            score.problems.append(f"a clarification must not give figures yet: {figures}")

    if applies["wording"]:
        score.wording_ok = says(answer.answer, gold["direction"])
        if not score.wording_ok:
            score.problems.append(f"the answer does not say {gold['direction']} (or negates it)")

    allowed = allowed_from(*seen)
    allowed.years |= question_years(question)
    checks = check_text(answer.answer + "\n" + (answer.clarifying_question or ""), allowed)
    score.ungrounded = [check.mention.text for check in checks if not check.grounded] + _structured_numbers(answer, allowed)
    score.unparsed = [check.mention.text for check in checks if check.mention.kind == "unparsed"]
    score.warnings = [term for term in gold.get("forbidden_terms", []) if term in answer.answer]

    score.automatic_passed = (score.status_ok and score.decision_ok and score.numbers_ok is not False
                              and score.basis_ok is not False and score.refusal_ok is not False
                              and score.wording_ok is not False and not score.ungrounded)
    return score


def _shown_status(case: dict[str, Any]) -> str | None:
    """The status of the answer actually shown, or None when nothing readable was shown."""
    if case["score"].get("format_error"):
        return None
    answer = case.get("answer")
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return None
    return answer.get("status") if isinstance(answer, dict) else None


def _rate(flags: list[bool]) -> dict[str, Any]:
    return {"correct": sum(flags), "total": len(flags)}


def summarize(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate run records (each with a "score" and run counters) into the metrics of EVAL_DESIGN section 5."""
    scores = [case["score"] for case in cases]
    model_latency = [case.get("model_latency_ms", 0) for case in cases]
    summary = {
        "cases": len(cases),
        "automatic_passed": _rate([score["automatic_passed"] for score in scores]),
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
        "evaluator_errors": sum(1 for case in cases if case.get("evaluator_error")),
        "warnings": sum(len(score["warnings"]) for score in scores),
        "model_attempts": sum(case.get("model_attempts", 0) for case in cases),
        "model_responses": sum(case.get("model_responses", 0) for case in cases),
        "tool_calls": sum(case.get("tool_call_count", 0) for case in cases),
        "model_latency_ms": {"total": round(sum(model_latency), 1),
                             "median_per_case": round(median(model_latency), 1) if model_latency else 0},
        "case_wall_ms_total": round(sum(case.get("wall_ms", 0) for case in cases), 1),
        "budget_exceeded": sum(1 for case in cases if case.get("budget_exceeded")),
        "failed": [score["id"] for score in scores if not score["automatic_passed"]],
        # how the failures failed (added for design B; pass/fail is unchanged)
        "confident_wrong": [case["score"]["id"] for case in cases if _shown_status(case) not in (None, "되묻기")
                            and not case["score"]["automatic_passed"]],
        "asked_back_instead": [case["score"]["id"] for case in cases if _shown_status(case) == "되묻기"
                               and not case["score"]["automatic_passed"]],
        # a reply cut off by the output limit (Codex 2026-10-08 review: counted, not hidden)
        "length_stops": [case["score"]["id"] for case in cases
                         if any(((request or {}).get("response") or {}).get("done_reason") == "length"
                                for request in case.get("requests") or [])],
    }
    paths = [(case.get("readings") or {}).get("used") for case in cases if case.get("readings")]
    if paths:  # the cross-check reading path of each question (EVAL_DESIGN 11.1)
        summary["reading_paths"] = {path: [case["score"]["id"] for case in cases
                                           if (case.get("readings") or {}).get("used") == path]
                                    for path in sorted({str(path) for path in paths})}
    for key in ("tool_args_first_ok", "tool_args_any_ok"):
        flags = [case[key] for case in cases if case.get(key) is not None]
        if flags:
            summary[key] = _rate(flags)
    return summary
