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

import run_eval  # noqa: E402
from scoring import summarize  # noqa: E402


def rescore_case(case: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """The runner's own scoring (run_eval.score_record), applied to the saved answer and tool results."""
    return {**case, "score": run_eval.score_record(dict(case), gold).to_dict()}


def golds_for(folder: Path) -> dict[str, dict[str, Any]]:
    """The gold answers of the run's question set (dev, paraphrase, or lookup), as the runner loaded them."""
    meta_path = folder / "run.json"
    question_set = json.loads(meta_path.read_text(encoding="utf-8")).get("question_set", "dev") if meta_path.exists() else "dev"
    return run_eval.load_questions(question_set)[1]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2 or not args[1].strip():
        print(__doc__)
        return 2
    folder, reason = Path(args[0]), args[1]
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()  # noqa: E731
    if git("status", "--porcelain", "--", "dart_review", "eval/scoring.py", "eval/rescore.py", "eval/run_eval.py"):
        print("commit the scorer first: a rescore must name the exact scorer it used")
        return 2
    commit = git("rev-parse", "--short", "HEAD")
    out_cases, out_report = folder / f"cases_rescored_{commit}.jsonl", folder / f"rescore_{commit}.json"
    if out_cases.exists() or out_report.exists():
        print(f"{out_report.name} exists; not overwritten")
        return 2
    gold = golds_for(folder)
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
