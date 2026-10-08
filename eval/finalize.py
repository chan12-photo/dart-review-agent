"""Human review of answer texts, and the final score that combines it with the automatic one.

    python eval/finalize.py <run folder>   # after filling <run folder>/human_review.json

The review criteria are fixed in eval/HUMAN_REVIEW.ko.md before any model run.
A question passes finally only if it passed automatically and its text passed
review. The one correction a reviewer may make to the automatic score is to
accept a number the scorer could not parse ("unparsed"); a number that failed
the rounding rule cannot be overridden.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "eval" / "dev_gold.json"
LOOKUP_GOLD = ROOT / "eval" / "dev_lookup_gold.json"  # value-lookup questions (EVAL_DESIGN 12.4), ids L01...
PASS_THRESHOLD = {"oracle": 0.8}  # SCOPE section 10: with the right evidence, 80% or more


class ReviewError(ValueError):
    pass


FAILURE_KINDS = ("수치", "설명")


def _gold() -> dict[str, dict[str, Any]]:
    answers = {}
    for path in (GOLD, LOOKUP_GOLD):
        for answer in json.loads(path.read_text(encoding="utf-8"))["answers"]:
            if answer["id"] in answers:
                raise ReviewError(f"question id {answer['id']} is in two gold files")
            answers[answer["id"]] = answer
    return answers


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
    if gold.get("scope"):
        parts.append({"company": "다루지 않는 회사", "companies": "회사 여러 개", "accounts": "계정 여러 개",
                      "account": "다루지 않는 계정"}[gold["scope"]] + f" ({gold['company']})")
    return " / ".join(part for part in parts if part)


def review_sheet(cases: Sequence[dict[str, Any]], golds: dict[str, dict[str, Any]] | None = None) -> str:
    """The sheet a reviewer reads. ``golds``: the run's own gold answers (a question file's gold, e.g. the 3-1
    sealed set); without it the development and lookup gold files are used (Codex 3-1 second review 1)."""
    gold = dict(golds) if golds is not None else _gold()
    for case in cases:  # a paraphrase is reviewed against its base question's gold
        if case["id"] not in gold and case.get("base") in gold:
            gold[case["id"]] = gold[case["base"]]
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
            "cases": {case["id"]: {"body_ok": None, "failure_kind": None, "note": "", "accepted_unparsed": []}
                      for case in cases}}


def write_review_files(folder: Path, cases: Sequence[dict[str, Any]], golds: dict[str, dict[str, Any]] | None = None) -> None:
    (folder / "review_sheet.md").write_text(review_sheet(cases, golds), encoding="utf-8")
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
        # a failed text says why: "수치" (a figure, period, basis, company, or account is wrong) or "설명" (the
        # figures are right but a reason is missing or a cause is asserted) - Codex 3-1 second review 5
        kind = entry.get("failure_kind")
        if entry["body_ok"] is False and kind not in FAILURE_KINDS:
            raise ReviewError(f"{case['id']}: a failed text needs failure_kind {FAILURE_KINDS}")
        per_case.append({"id": case["id"], "automatic_passed": automatic, "automatic_after_accepted_notation": corrected,
                         "body_ok": entry["body_ok"], "reviewed_passed": corrected and entry["body_ok"],
                         "failure_kind": kind if entry["body_ok"] is False else None,
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
    if len(args) not in (1, 2):
        print("usage: python eval/finalize.py <run folder> [cases file, e.g. cases_rescored_<commit>.jsonl]")
        return 2
    folder = Path(args[0])
    cases_name = args[1] if len(args) == 2 else "cases.jsonl"
    cases = [json.loads(line) for line in (folder / cases_name).read_text(encoding="utf-8").splitlines() if line]
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    review = json.loads((folder / "human_review.json").read_text(encoding="utf-8"))
    result = final_scores(cases, review, meta["mode"])
    # tie the review to the exact run it judged (Codex 3-1 second review 3)
    result.update(cases_file=cases_name, cases_sha256=hashlib.sha256((folder / cases_name).read_bytes()).hexdigest(),
                  run_sha256=hashlib.sha256((folder / "run.json").read_bytes()).hexdigest(),
                  review_sha256=hashlib.sha256((folder / "human_review.json").read_bytes()).hexdigest())
    base = "final" if cases_name == "cases.jsonl" else f"final_{Path(cases_name).stem}"
    out, version = folder / f"{base}.json", 1
    while out.exists():  # a re-review never overwrites: it is a new version, with its reason
        version += 1
        out = folder / f"{base}_v{version}.json"
    if version > 1:
        if not review.get("revision_reason"):
            print(f"{base}.json exists: a revised review needs 'revision_reason' in human_review.json")
            return 2
        result["revision"] = {"version": version, "reason": review["revision_reason"]}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "per_case"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
