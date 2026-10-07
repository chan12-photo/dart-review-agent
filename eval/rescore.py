"""Score a finished run again with the current scorer, without running the model again.

    python eval/rescore.py <run folder> "<reason>"

Used only when the scorer itself was wrong (EVAL_DESIGN: a rule changed after
seeing results is reported with the reason and both scores). The original
cases.jsonl and summary.json are never changed; this writes
cases_rescored_<commit>.jsonl and rescore_<commit>.json next to them.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from scoring import CaseScore, score_case, summarize  # noqa: E402

GOLD = ROOT / "eval" / "dev_gold.json"


def rescore_case(case: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """The same scoring path as run_eval.run_case, applied to the saved answer and tool results."""
    if case.get("evaluator_error") and case.get("answer") is None:
        score = CaseScore(case["id"], format_error="evaluator error")
    else:
        score = score_case(gold, case.get("answer"), case.get("seen", []), case["question"])
    if case.get("model_error"):
        score.format_error = f"model error: {case['model_error']}"
    elif case.get("evaluator_error"):
        score.format_error = "evaluator error"
    elif case.get("budget_exceeded"):
        score.format_error = "budget exceeded (no final answer)"
    if case.get("model_error") or case.get("evaluator_error") or case.get("budget_exceeded"):
        score.automatic_passed = False
    return {**case, "score": score.to_dict()}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or not args[1].strip():
        print(__doc__)
        return 2
    folder, reason = Path(args[0]), args[1]
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    if git("status", "--porcelain", "--", "dart_review", "eval/scoring.py", "eval/rescore.py"):
        print("commit the scorer first: a rescore must name the exact scorer it used")
        return 2
    commit = git("rev-parse", "--short", "HEAD")
    out_cases, out_report = folder / f"cases_rescored_{commit}.jsonl", folder / f"rescore_{commit}.json"
    if out_cases.exists() or out_report.exists():
        print(f"{out_report.name} exists; not overwritten")
        return 2
    gold = {answer["id"]: answer for answer in json.loads(GOLD.read_text(encoding="utf-8"))["answers"]}
    original = [json.loads(line) for line in (folder / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line]
    rescored = [rescore_case(case, gold[case["id"]]) for case in original]
    with out_cases.open("w", encoding="utf-8") as handle:
        for case in rescored:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")
    changed = [{"id": before["id"],
                "before": {key: before["score"][key] for key in ("automatic_passed", "ungrounded", "unparsed", "problems")},
                "after": {key: after["score"][key] for key in ("automatic_passed", "ungrounded", "unparsed", "problems")}}
               for before, after in zip(original, rescored) if before["score"] != after["score"]]
    report = {"scorer_commit": commit, "reason": reason, "before": summarize(original), "after": summarize(rescored),
              "changed_cases": changed}
    out_report.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"before": report["before"]["automatic_passed"], "after": report["after"]["automatic_passed"],
                      "changed": [item["id"] for item in changed]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
