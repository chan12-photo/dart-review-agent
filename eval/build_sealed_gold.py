"""Build the 3-1 sealed gold answers (docs/EVAL_CONTRACT_3-1.ko.md sections 1 step 5, 4.5, and 6).

The independent parts of eval/build_gold.py and eval/build_lookup_gold.py are
reused unchanged: evidence cells named by hand in eval/sealed_3-1/questions.json,
read straight from the cached responses, periods from their own column table.
The company names come from the sealed set instead of the development one.

Unlike the development builders, a disagreement with the product's rules does
not stop the build (contract section 1): every disagreement is written to
eval/sealed_3-1/gold_disagreements.json for a human decision (section 4.5),
and the gold is written as specified.

    python eval/build_sealed_gold.py          # write gold.json and gold_disagreements.json
    python eval/build_sealed_gold.py --check  # fail if either committed file is stale
"""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import build_gold  # noqa: E402
import build_lookup_gold  # noqa: E402
from build_gold import GoldError  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import SEALED_EVAL_COMPANIES, using_company_set  # noqa: E402

FOLDER = ROOT / "eval" / "sealed_3-1"
SPEC, GOLD, DISAGREEMENTS = FOLDER / "questions.json", FOLDER / "gold.json", FOLDER / "gold_disagreements.json"
LOOKUP_ACTIONS = ("lookup", "clarify_company", "out_of_scope")


def build(client: DartClient, spec: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    reference_date = date.fromisoformat(spec["reference_date"])
    answers, disagreements = [], []
    with using_company_set("sealed-3-1"), \
            mock.patch.object(build_gold, "DEV_COMPANIES", SEALED_EVAL_COMPANIES), \
            mock.patch.object(build_lookup_gold, "DEV_COMPANIES", SEALED_EVAL_COMPANIES):
        for question in spec["questions"]:
            action = question["expected"]["action"]
            if action == "lookup":
                gold = build_lookup_gold.build_lookup(client, question)
            elif action in ("clarify_company", "out_of_scope"):
                gold = build_lookup_gold.build_other(question)
            else:
                gold = build_gold.build_question(client, question)
            gold.update(bundle=question["bundle"], author=question["author"])
            try:
                problems = (build_lookup_gold.cross_check(client, question, gold, reference_date) if action in LOOKUP_ACTIONS
                            else build_gold.cross_check(client, question, gold))
            except Exception as exc:  # the product's rules failing on a question is a finding, not a build error
                problems = [f"the product's rules raised {type(exc).__name__}: {exc}"]
            if problems:
                disagreements.append({"id": question["id"], "question": question["question"], "gold_status": gold.get("status"),
                                      "problems": problems, "decision": None, "reason": None, "approved_by_user": False})
            answers.append(gold)
    document = {"version": spec["version"], "source": "eval/sealed_3-1/questions.json", "reference_date": spec["reference_date"],
                "answers": answers}
    return document, disagreements


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    client = DartClient(ResponseCache(ROOT / "cache"), key_loader=build_gold.no_key, offline=True)
    try:
        document, disagreements = build(client, json.loads(SPEC.read_text(encoding="utf-8")))
    except GoldError as exc:
        print(f"the hand-written expectation is inconsistent with the raw data: {exc}")
        return 1
    gold_text = json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if args.check:
        stale = GOLD.read_text(encoding="utf-8") != gold_text if GOLD.exists() else True
        recorded = json.loads(DISAGREEMENTS.read_text(encoding="utf-8")) if DISAGREEMENTS.exists() else {"items": []}
        found = [(item["id"], item["problems"]) for item in disagreements]
        # a disagreement resolved by correcting the gold disappears from the build but stays in the record
        open_items = [(item["id"], item["problems"]) for item in recorded["items"] if not item.get("decision", "").startswith("정답 수정")]
        same = found == open_items
        print(f"{len(document['answers'])} answers; gold.json {'STALE' if stale else 'up to date'}; "
              f"disagreements {'match' if same else 'DIFFER from'} the recorded list ({len(found)})")
        return 0 if not stale and same else 1
    GOLD.write_text(gold_text, encoding="utf-8")
    if not DISAGREEMENTS.exists():  # decisions are filled in by hand afterwards; never overwritten here
        DISAGREEMENTS.write_text(json.dumps({"about": "contract 4.5: each item is decided by re-reading the raw cells and "
                                             "approved by the user before any model run", "items": disagreements},
                                            ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(document['answers'])} answers -> {GOLD.relative_to(ROOT)}; {len(disagreements)} disagreements with the rules")
    for item in disagreements:
        print(f"  {item['id']}: {item['problems']}")
    network = client.network_requests
    return 0 if network == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
