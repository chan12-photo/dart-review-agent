"""Human review of answer texts, and the final score that combines it with the automatic one.

    python eval/finalize.py <run folder>   # after filling <run folder>/human_review.json

The review criteria are fixed in eval/HUMAN_REVIEW.ko.md before any model run.
A question passes finally only if it passed automatically and its text passed
review. The one correction a reviewer may make to the automatic score is to
accept a number the scorer could not parse ("unparsed"); a number that failed
the rounding rule cannot be overridden.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "dev_gold.json"
PASS_THRESHOLD = {"oracle": 0.8}  # SCOPE section 10: with the right evidence, 80% or more


class ReviewError(ValueError):
    pass


def _gold() -> dict[str, dict[str, Any]]:
    return {answer["id"]: answer for answer in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}


def _expected_summary(gold: dict[str, Any]) -> str:
    if gold["decision"] == "clarify":
        return "되묻기 (" + ", ".join(option["label"] for option in gold["options"]) + ")"
    parts = [gold["expected_status"], gold.get("basis", ""), gold.get("account_label", "")]
    if "current_period" in gold:
        parts.append(f"{gold['current_period']} 대 {gold['base_period']}")
    elif "period" in gold:
        parts.append(gold["period"])
    if gold.get("direction"):
        parts.append(gold["direction"])
    return " / ".join(part for part in parts if part)


def review_sheet(cases: Sequence[dict[str, Any]]) -> str:
    gold = _gold()
    lines = ["# 본문 검토지", "", "기준: eval/HUMAN_REVIEW.ko.md (공통 1~5번과 문항별 확인 사항). 판정은 human_review.json에 적는다.", ""]
    for case in cases:
        score, answer = case["score"], case.get("answer")
        try:
            parsed = json.loads(answer) if isinstance(answer, str) else answer
        except ValueError:
            parsed = None
        lines += [f"## {case['id']}", "", f"- 질문: {case['question']}", f"- 정답: {_expected_summary(gold[case['id']])}",
                  f"- 자동 채점: {'통과' if score['automatic_passed'] else '실패'}"
                  + (f" ({score['format_error']})" if score.get("format_error") else "")]
        if score.get("problems"):
            lines.append(f"- 자동 채점 문제: {' / '.join(score['problems'])}")
        if score.get("ungrounded"):
            lines.append(f"- 근거 없는 숫자: {score['ungrounded']} (판정 불가 표기: {score.get('unparsed', [])})")
        if isinstance(parsed, dict):
            lines += [f"- 상태: {parsed.get('status')}", "", "> " + str(parsed.get("answer", "")).replace("\n", "\n> ")]
            if parsed.get("clarifying_question"):
                lines += ["", f"> (되묻는 질문) {parsed['clarifying_question']}"]
        else:
            lines += ["", "> (읽을 수 있는 답이 없음)"]
        lines.append("")
    return "\n".join(lines)


def review_template(cases: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return {"reviewer": "", "confirmed_by_user": False, "criteria": "eval/HUMAN_REVIEW.ko.md",
            "cases": {case["id"]: {"body_ok": None, "note": "", "accepted_unparsed": []} for case in cases}}


def write_review_files(folder: Path, cases: Sequence[dict[str, Any]]) -> None:
    (folder / "review_sheet.md").write_text(review_sheet(cases), encoding="utf-8")
    template = folder / "human_review.json"
    if not template.exists():
        template.write_text(json.dumps(review_template(cases), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _passes_after_accepting(score: dict[str, Any], accepted: list[str]) -> bool:
    if not set(accepted) <= set(score.get("unparsed", [])):
        raise ReviewError(f"{score['id']}: only unparsed notations can be accepted, not {accepted}")
    remaining = [item for item in score["ungrounded"] if item not in accepted]
    return (not score["format_error"] and score["status_ok"] and score["decision_ok"]
            and all(score[key] is not False for key in ("numbers_ok", "basis_ok", "refusal_ok", "wording_ok"))
            and not remaining)


def final_scores(cases: Sequence[dict[str, Any]], review: dict[str, Any], mode: str) -> dict[str, Any]:
    per_case, missing = [], []
    for case in cases:
        entry = review["cases"].get(case["id"])
        if entry is None or not isinstance(entry.get("body_ok"), bool):
            missing.append(case["id"])
            continue
        accepted = entry.get("accepted_unparsed", [])
        automatic = case["score"]["automatic_passed"]
        corrected = automatic or _passes_after_accepting(case["score"], accepted)
        per_case.append({"id": case["id"], "automatic_passed": automatic, "automatic_after_accepted_notation": corrected,
                         "body_ok": entry["body_ok"], "reviewed_passed": corrected and entry["body_ok"],
                         "note": entry.get("note", ""), "accepted_unparsed": accepted})
    if missing:
        raise ReviewError(f"body_ok must be true or false for every question; missing: {missing}")
    total = len(per_case)
    reviewed = sum(item["reviewed_passed"] for item in per_case)
    result = {"mode": mode, "reviewer": review.get("reviewer"), "confirmed_by_user": review.get("confirmed_by_user"),
              "automatic_passed": sum(item["automatic_passed"] for item in per_case),
              "reviewed_passed": reviewed, "total": total, "per_case": per_case}
    if mode in PASS_THRESHOLD:
        needed = -(-int(PASS_THRESHOLD[mode] * 100) * total // 100)  # ceiling, no float rounding
        result["threshold"] = {"needed": needed, "met": reviewed >= needed}
    return result


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: python eval/finalize.py <run folder>")
        return 2
    folder = Path(args[0])
    cases = [json.loads(line) for line in (folder / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    review = json.loads((folder / "human_review.json").read_text(encoding="utf-8"))
    result = final_scores(cases, review, meta["mode"])
    (folder / "final.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "per_case"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
