"""Classify results and judge a 3-1 style evaluation (docs/EVAL_CONTRACT_3-1.ko.md sections 8 and 9).

    python eval/judge.py --crosscheck DIR [--baseline DIR] [--model-only DIR] [--final MODE=FILE ...] [--out FILE]

For each question, the product result is put in one cell of the outcome table
(section 8) from the answer actually shown. The interpretation table uses the
two reading keys the cross-check run recorded; the expected key comes from the
hand-written expectation of the question, normalized by the same function the
product uses. Before any criterion is applied, the runs are checked (Codex B10):
every gold question exactly once, no duplicate, no evaluator error, the same
question set, company set, reference date, prompt version and code, a clean
tree. If any check fails, the verdict is "판정 보류" with the reasons; the
criteria are not applied.

By default the judge is strict (the 3-1 contract, Codex 3-1 first review 3):
all three methods, a complete human review confirmed by the user for every
method (so a refusal or clarification with the wrong reason fails through the
review, finding 4), the fixed 36-question composition for the sealed set, the
same model identity, the recorded file hashes equal to the files read now,
reading keys recorded, and every criterion applicable. Otherwise the verdict
is "판정 보류". --exploratory relaxes these for development sets and marks the
report "탐색 (판정 아님)"; automatic scores are then used where no review is given.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import run_eval  # noqa: E402
from dart_review.companies import FS_DIVS, supported_companies, using_company_set  # noqa: E402
from dart_review.crosscheck import canonical  # noqa: E402

ANSWER_STATUSES = ("값 확인", "비교 가능", "확인 필요", "나란히 표시")
REFUSAL_STATUSES = ("범위 밖", "비교 불가", "조회 불가", "데이터 없음")
OUTCOMES = ("정답 제공", "맞는 거절", "맞는 되묻기", "불필요한 되묻기", "잘못된 되묻기", "보류·무응답", "잘못된 수치 답", "잘못된 거절",
            "설명 실패")
SOLVED = ("정답 제공", "맞는 거절", "맞는 되묻기")
COSTS = ("불필요한 되묻기", "보류·무응답", "잘못된 거절")
# docs/EVAL_CONTRACT_3-1.ko.md section 10 (decided by the user before any sealed data)
CRITERIA = {"wrong_answers": 0, "solved_rate": 0.70, "cost_rate": 0.25, "out_of_scope_rate": 0.75}
METHODS = ("crosscheck", "baseline", "model_only")
# section 4.1: bundle -> author -> count
COMPOSITION_3_1 = {"A": {"claude": 16}, "B": {"user": 10}, "C": {"claude": 6, "user": 4}}
HASHED_FILES = ("questions", "gold", "paraphrases", "lookup_questions", "lookup_gold", "set_questions", "set_gold",
                "reading_prompt", "reading_schema", "company_set")


def freeze(value: Any) -> Any:
    """A key as the product builds it: JSON turns its inner tuples into lists (Codex 3-1 first review 2)."""
    return tuple(freeze(item) for item in value) if isinstance(value, (list, tuple)) else value


def expected_key(question: dict[str, Any]) -> tuple | None:
    """The reading the question should get, normalized by the product's own canonical form."""
    expected = question["expected"]
    action = expected["action"]
    if action == "clarify_company":
        return canonical("clarify_company", None, expected["company"])
    if action == "out_of_scope":
        return canonical("unsupported", {}, expected["company"])
    company = supported_companies()[expected["corp_code"]]
    if action == "clarify":
        return canonical("clarify", None, company, expected["options"])
    if action == "side_by_side":
        return canonical("side_by_side", {"account": expected["account"], "period": expected["period"]}, company)
    basis = FS_DIVS[expected["fs_div"]]
    if action == "lookup":
        return canonical("lookup", {"basis": basis, "account": expected["account"], "period": expected["period"]}, company)
    return canonical("compare", {"basis": basis, "account": expected["account"], "current_period": expected["current"],
                                 "base_period": expected["base"]}, company)


def shown_answer(case: dict[str, Any]) -> dict[str, Any] | None:
    answer = case.get("answer")
    if isinstance(answer, str):
        try:
            answer = json.loads(answer)
        except ValueError:
            return None
    return answer if isinstance(answer, dict) and case["score"].get("format_error") is None else None


def outcome(case: dict[str, Any], gold: dict[str, Any], passed: bool, failure_kind: str | None = None) -> str:
    """One cell of the outcome table (contract section 8), from what was shown.

    An answer whose automatic score passed but whose text failed review for its explanation only ("설명") is
    "설명 실패", not a wrong figure (Codex 3-1 second review 5).
    """
    answer = shown_answer(case)
    if answer is None:
        return "보류·무응답"
    status, decision = answer.get("status"), gold["decision"]
    if status == "되묻기":
        if decision == "clarify":
            return "맞는 되묻기" if passed else "잘못된 되묻기"
        return "불필요한 되묻기"
    if status in REFUSAL_STATUSES:
        return "맞는 거절" if decision == "refuse" and passed else "잘못된 거절"
    if status in ANSWER_STATUSES:
        if passed:
            return "정답 제공"
        if failure_kind == "설명" and case["score"].get("automatic_passed"):
            return "설명 실패"
        return "잘못된 수치 답"
    return "잘못된 수치 답"  # an unknown status shown to the user is never counted as safe


def load_run(folder: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    data = (folder / "cases.jsonl").read_bytes()
    meta["_cases_sha256"] = hashlib.sha256(data).hexdigest()  # what a human review must name (second review 3)
    return meta, [json.loads(line) for line in data.decode("utf-8").splitlines() if line]


def check_runs(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], gold_ids: list[str]) -> list[str]:
    """Reasons the runs cannot be judged (Codex B10); empty when they can."""
    problems = []
    metas = {mode: meta for mode, (meta, _) in runs.items()}
    for key in ("question_set", "company_set", "reference_date"):
        values = {mode: meta.get(key) for mode, meta in metas.items()}
        if len(set(values.values())) != 1:
            problems.append(f"{key} differs between runs: {values}")
    commits = {mode: (meta.get("git") or {}).get("commit") for mode, meta in metas.items()}
    if len(set(commits.values())) != 1:
        problems.append(f"the runs ran different code: {commits}")
    shared = ("questions", "gold", "lookup_questions", "lookup_gold", "set_questions", "set_gold", "reading_prompt",
              "reading_schema", "company_set")
    for key in shared:
        values = {mode: (meta.get("contract") or {}).get(key) for mode, meta in metas.items()}
        if len(set(values.values())) != 1:
            problems.append(f"contract {key} differs between runs")
    for mode, (meta, cases) in runs.items():
        if (meta.get("git") or {}).get("dirty"):
            problems.append(f"{mode}: run from a dirty tree")
        ids = [case["id"] for case in cases]
        duplicates = sorted(item for item, count in Counter(ids).items() if count > 1)
        missing, extra = sorted(set(gold_ids) - set(ids)), sorted(set(ids) - set(gold_ids))
        if duplicates or missing or extra:
            problems.append(f"{mode}: duplicates {duplicates}, missing {missing}, unexpected {extra}")
        errors = [case["id"] for case in cases if case.get("evaluator_error")]
        if errors:
            problems.append(f"{mode}: evaluator errors {errors}")
    return problems


def _reading_state(key: Any, expected: tuple | None, failed: str | None = None) -> str:
    if key is None:
        return failed or "미해석"
    return "정답" if freeze(key) == freeze(expected) else "오답"


def check_contract(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], finals: dict[str, dict[str, Any]],
                   questions: dict[str, dict[str, Any]]) -> list[str]:
    """What the strict (3-1) judge also requires (Codex 3-1 first review 3); empty when all is there."""
    problems = []
    missing = [method for method in METHODS if method not in runs]
    if missing:
        problems.append(f"methods missing: {missing}")
    meta = runs["crosscheck"][0]
    current = run_eval.contract_hashes(meta.get("question_set", "dev"))
    for method, (method_meta, _) in runs.items():  # every run, not only the cross-check one (second review 2)
        recorded = method_meta.get("contract") or {}
        changed = [key for key in HASHED_FILES if key in current and recorded.get(key) != current[key]]
        if changed:
            problems.append(f"{method}: the files read now differ from the ones the run recorded: {changed}")
    models = {method: {key: (runs[method][0].get("model") or {}).get(key) for key in ("model", "digest", "options", "think")}
              for method in ("crosscheck", "model_only") if method in runs}
    if len({json.dumps(model, sort_keys=True) for model in models.values()}) > 1:
        problems.append(f"the model differs between methods: {models}")
    without_keys = [case["id"] for case in runs["crosscheck"][1]
                    if "rule_key" not in (case.get("readings") or {}) or "model_key" not in (case.get("readings") or {})]
    if without_keys:
        problems.append(f"crosscheck cases without recorded reading keys: {without_keys}")
    for method, (_, cases) in runs.items():
        final = finals.get(method)
        if not final:
            problems.append(f"{method}: no human review result")
            continue
        reviewed = {item["id"]: item for item in final.get("per_case", [])}
        if set(reviewed) != {case["id"] for case in cases}:
            problems.append(f"{method}: the review covers {sorted(reviewed)}, not the run's questions")
        if not final.get("confirmed_by_user"):
            problems.append(f"{method}: the review is not confirmed by the user")
        mismatched = [case["id"] for case in cases if case["id"] in reviewed
                      and reviewed[case["id"]].get("automatic_passed") != case["score"]["automatic_passed"]]
        if mismatched:
            problems.append(f"{method}: the review belongs to another run (automatic scores differ: {mismatched})")
        if any(not isinstance(item.get("reviewed_passed"), bool) for item in reviewed.values()):
            problems.append(f"{method}: a reviewed result is not true or false")
        run_meta = runs[method][0]
        if final.get("mode") != run_meta.get("mode") or final.get("cases_sha256") != run_meta.get("_cases_sha256"):
            problems.append(f"{method}: the review names another run (mode {final.get('mode')}, cases "
                            f"{str(final.get('cases_sha256'))[:12]}) than this one ({run_meta.get('mode')}, "
                            f"{str(run_meta.get('_cases_sha256'))[:12]})")
    if meta.get("company_set") == "sealed-3-1":
        changed = run_eval.frozen_differences((meta.get("git") or {}).get("commit") or "HEAD")
        if changed:
            problems.append(f"the runs' code differs from the freeze commit P: {changed}")
        found: dict[str, Counter] = {}
        for question in questions.values():
            found.setdefault(question.get("bundle"), Counter())[question.get("author")] += 1
        expected = {bundle: Counter(authors) for bundle, authors in COMPOSITION_3_1.items()}
        if found != expected:
            problems.append(f"the questions are not the contract's 36 (bundle -> authors): {found}")
    return problems


def judge(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], finals: dict[str, dict[str, Any]] | None = None,
          exploratory: bool = False) -> dict[str, Any]:
    finals = finals or {}
    meta = runs["crosscheck"][0]
    with using_company_set(meta.get("company_set", "development")):
        questions, golds = run_eval.load_questions(meta.get("question_set", "dev"))
        by_id = {question["id"]: question for question in questions}
        problems = check_runs(runs, list(by_id))
        if not exploratory and not problems:
            problems += check_contract(runs, finals, by_id)
    report: dict[str, Any] = {"question_set": meta.get("question_set"), "company_set": meta.get("company_set"),
                              "reference_date": meta.get("reference_date"), "prompt_version": meta.get("prompt_version"),
                              "commit": (meta.get("git") or {}).get("commit"), "problems": problems,
                              "review": {mode: ({"confirmed_by_user": final.get("confirmed_by_user")} if final else "사람 검토 전")
                                         for mode, final in ((mode, finals.get(mode)) for mode in runs)}}
    report["exploratory"] = exploratory
    if problems:
        report["verdict"] = "판정 보류"
        return report
    with using_company_set(meta.get("company_set", "development")):
        expected = {question_id: freeze(expected_key(question)) for question_id, question in by_id.items()}
    outcomes: dict[str, dict[str, str]] = {}
    for mode, (_, cases) in runs.items():
        reviewed = {item["id"]: item for item in (finals.get(mode) or {}).get("per_case", [])}
        outcomes[mode] = {case["id"]: outcome(case, golds[case["id"]],
                                              reviewed.get(case["id"], {}).get("reviewed_passed", case["score"]["automatic_passed"]),
                                              reviewed.get(case["id"], {}).get("failure_kind"))
                          for case in cases}
    cross = {case["id"]: case for case in runs["crosscheck"][1]}

    # interpretation table (both keys recorded by the cross-check run)
    interpretation: dict[str, list[str]] = {}
    for question_id, case in cross.items():
        readings = case.get("readings") or {}
        model_failed = None
        if readings.get("model_key") is None:
            length = any(((request or {}).get("response") or {}).get("done_reason") == "length" for request in case.get("requests") or [])
            model_failed = "미해석(출력 한도)" if length else "미해석(형식)" if readings.get("model_error") or case.get("model_error") else "미해석"
        rule_key = readings.get("rule_key")
        if "rule_key" not in readings or "model_key" not in readings:
            cell = "해석 키 기록 없음"  # a run made before the keys were recorded: unknown, not "미해석"
        else:
            cell = (f"규칙 {_reading_state(rule_key, expected[question_id])} / "
                    f"모델 {_reading_state(readings.get('model_key'), expected[question_id], model_failed)}")
        interpretation.setdefault(cell, []).append(question_id)

    # product outcome table, per method
    table = {mode: {name: [item for item, cell in result.items() if cell == name] for name in OUTCOMES}
             for mode, result in outcomes.items()}

    # what the cross-check changed, against the single-reader runs
    singles = [mode for mode in ("baseline", "model_only") if mode in outcomes]
    effect = {
        "막은 오답": [item for item, cell in outcomes["crosscheck"].items() if cell != "잘못된 수치 답"
                  and any(outcomes[mode][item] == "잘못된 수치 답" for mode in singles)],
        "잃은 정답": [item for item, cell in outcomes["crosscheck"].items() if cell not in SOLVED
                  and any(outcomes[mode][item] in SOLVED for mode in singles)],
        "일치한 오답": [item for item, cell in outcomes["crosscheck"].items() if cell == "잘못된 수치 답"
                   and (cross[item].get("readings") or {}).get("used") == "both"],
        "한쪽 해석으로 낸 답": [item for item, case in cross.items() if (case.get("readings") or {}).get("used") == "model only"
                         and shown_answer(case) is not None],
    }

    # practical cost and the criteria (cross-check only, contract section 9)
    answerable = [item for item in by_id if golds[item]["decision"] in ("answer", "side_by_side")]
    product = outcomes["crosscheck"]
    shown_answers = [item for item, cell in product.items() if cell in ("정답 제공", "잘못된 수치 답")]
    cost = {mode: {"solved_answerable": sum(result[item] == "정답 제공" for item in answerable),
                   "answerable": len(answerable),
                   "wrong_among_answers": sum(cell == "잘못된 수치 답" for cell in result.values()),
                   "asked_back": sum(cell in ("맞는 되묻기", "불필요한 되묻기", "잘못된 되묻기") for cell in result.values()),
                   "model_seconds": round(sum(case.get("model_latency_ms", 0) for case in runs[mode][1]) / 1000, 1),
                   "length_stops": [case["id"] for case in runs[mode][1]
                                    if any(((request or {}).get("response") or {}).get("done_reason") == "length"
                                           for request in case.get("requests") or [])]}
            for mode, result in outcomes.items()}
    ungrounded = {mode: [case["id"] for case in cases if case["score"].get("ungrounded")] for mode, (_, cases) in runs.items()}
    out_of_scope = [item for item, question in by_id.items() if question.get("bundle") == "C"]
    solved_rate = cost["crosscheck"]["solved_answerable"] / len(answerable) if answerable else None
    cost_rate = (sum(product[item] in COSTS for item in answerable) / len(answerable)) if answerable else None
    scope_rate = (sum(product[item] in ("맞는 거절", "맞는 되묻기") for item in out_of_scope) / len(out_of_scope)
                  if out_of_scope else None)
    checks = {
        "잘못된 수치 답 0": {"value": len(table["crosscheck"]["잘못된 수치 답"]), "met": not table["crosscheck"]["잘못된 수치 답"]},
        "해결률 ≥ 70%": {"value": solved_rate, "met": solved_rate is not None and solved_rate >= CRITERIA["solved_rate"]},
        "비용 ≤ 25%": {"value": cost_rate, "met": cost_rate is not None and cost_rate <= CRITERIA["cost_rate"]},
        "범위 밖·모호 ≥ 75%": {"value": scope_rate, "met": None if scope_rate is None else scope_rate >= CRITERIA["out_of_scope_rate"]},
        "근거 없는 숫자 0": {"value": ungrounded, "met": not any(ungrounded.values())},
    }
    report.update(outcomes=outcomes, outcome_table=table, interpretation=interpretation, crosscheck_effect=effect,
                  cost=cost, checks=checks, shown_answers=len(shown_answers))
    unknown = [name for name, check in checks.items() if check["met"] is None]
    if exploratory:
        report["verdict"] = "탐색 (판정 아님)"
    elif unknown:  # a criterion that cannot be applied is not a pass (Codex 3-1 first review 3)
        report["verdict"] = "판정 보류"
        report["problems"].append(f"criteria that cannot be applied: {unknown}")
    else:
        report["verdict"] = "기준 충족" if all(check["met"] for check in checks.values()) else "기준 미달"
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--crosscheck", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--model-only", type=Path)
    parser.add_argument("--final", action="append", default=[], help="MODE=FILE: a finalize.py result for that method")
    parser.add_argument("--out", type=Path, help="write the report as JSON (never over an existing file)")
    parser.add_argument("--exploratory", action="store_true",
                        help="development sets: relax the 3-1 requirements; the report is not a verdict")
    args = parser.parse_args(argv)
    runs = {mode: load_run(folder) for mode, folder in
            (("crosscheck", args.crosscheck), ("baseline", args.baseline), ("model_only", args.model_only)) if folder}
    finals = {}
    for item in args.final:
        mode, _, path = item.partition("=")
        finals[mode] = json.loads(Path(path).read_text(encoding="utf-8"))
    report = judge(runs, finals, exploratory=args.exploratory)
    text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        if args.out.exists():
            parser.error(f"{args.out} exists; reports are never overwritten")
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["verdict"] != "판정 보류" else 1


if __name__ == "__main__":
    raise SystemExit(main())
