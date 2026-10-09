"""Classify results and judge a 3-1 or 3-5 evaluation (docs/EVAL_CONTRACT_3-1.ko.md sections 8-9, 3-5 sections 6-9).

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

A question file may name its contract ("contract": "3-5"). The 3-5 template evaluation is judged with its own
methods (cross-check and rules only), composition (600 questions by family), freeze record, sampled human
review, criteria, and suspension conditions (decided gold disagreements, model-server failures at most 2%);
its report adds tables by family and by group, the two directions of a wrong figure, the company x basis x
account clusters with a wrong figure, and the 95% upper bound of the wrong-figure rate.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import finalize  # noqa: E402
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
# EVAL_CONTRACT_3-5 sections 4.2, 9, 10 (decided by the user 2026-10-09, before any question existed)
COMPOSITION_3_5 = {"A1": 60, "A2": 60, "A3": 60, "A4": 60, "A5": 60, "A6": 80, "A7": 40, "A8": 60,
                   "B1": 25, "B2": 20, "B3": 15, "B4": 15, "B5": 15, "B6": 10, "B7": 10, "B8": 10}
CRITERIA_3_5 = {"wrong_answers": 0, "solved_rate": 0.80, "trap_rate": 0.90}
METHODS_3_5 = ("crosscheck", "baseline")
INFRASTRUCTURE_LIMIT_3_5 = 0.02  # section 9: model-server failures above this suspend the verdict
# section 2 and 7 (Codex 3-5 review 1): checked against the contract, not only between the two runs
REFERENCE_DATE_3_5, COMPANY_SET_3_5, FREEZE_3_5 = "2026-10-08", "sealed-3-1", "eval/freeze_3-5.json"
PRODUCT_3_5 = "db756c240f1af955a1052e62e2c60345b4d5942b"  # P3, v0.1.1
EVALUATOR_PATHS_3_5 = ("eval/run_eval.py", "eval/scoring.py", "eval/judge.py", "eval/finalize.py", "eval/rescore.py",
                       "eval/build_template_questions.py", "eval/build_template_gold.py")
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


RUN_RECORDS_3_5 = "eval/template_3-5/runs/"


def only_run_records_between(commits: dict[str, str | None], metas: dict[str, dict[str, Any]]) -> bool:
    """Amendment P5 (EVAL_CONTRACT_3-5 section 9.1, after the runs): the contract commits each run before the next,
    so the 3-5 runs name different commits. They count as the same code when everything between them is a run
    record in eval/template_3-5/runs/; each run's commit is still compared with the freeze record."""
    if {contract_of(meta.get("question_set")) for meta in metas.values()} != {"3-5"} or None in commits.values():
        return False
    first, *others = sorted(set(commits.values()))
    for other in others:
        result = subprocess.run(["git", "diff", "--name-only", first, other], cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0 or any(not path.startswith(RUN_RECORDS_3_5) for path in result.stdout.split()):
            return False
    return True


def check_runs(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], gold_ids: list[str]) -> list[str]:
    """Reasons the runs cannot be judged (Codex B10); empty when they can."""
    problems = []
    metas = {mode: meta for mode, (meta, _) in runs.items()}
    for key in ("question_set", "company_set", "reference_date"):
        values = {mode: meta.get(key) for mode, meta in metas.items()}
        if len(set(values.values())) != 1:
            problems.append(f"{key} differs between runs: {values}")
    commits = {mode: (meta.get("git") or {}).get("commit") for mode, meta in metas.items()}
    if len(set(commits.values())) != 1 and not only_run_records_between(commits, metas):
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


def contract_of(question_set: str | None) -> str:
    """The contract a question file names ("3-5"); every other set is judged as in 3-1."""
    if question_set and question_set.startswith(run_eval.FILE_SET):
        return json.loads(run_eval.set_files(question_set)[0].read_text(encoding="utf-8")).get("contract", "3-1")
    return "3-1"


def check_sampled_reviews(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], finals: dict[str, dict[str, Any]],
                          golds: dict[str, dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    """EVAL_CONTRACT_3-5 section 8: every failure, the drawn sample, and any widened family were reviewed."""
    problems = []
    for method, (_, cases) in runs.items():
        final = finals.get(method) or {}
        per_case = {item["id"]: item for item in final.get("per_case", [])}
        if final.get("sample") != finalize.review_sample(cases, policy, method):
            problems.append(f"{method}: the reviewed sample is not the one the policy draws")
        entries = {item: {"body_ok": entry.get("body_ok"), "failure_kind": entry.get("failure_kind")}
                   for item, entry in per_case.items() if entry.get("reviewed")}
        required, _ = finalize.required_reviews(cases, policy, method, golds, {"cases": entries})
        unreviewed = [item for item in required if not (per_case.get(item) or {}).get("reviewed")]
        if unreviewed:
            problems.append(f"{method}: required reviews missing: {unreviewed}")
    return problems


def check_fixed_3_5(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], question_set: str) -> list[str]:
    """The 3-5 runs against the contract and the pre-registration record, not only against each other."""
    problems = []
    question_file, gold_file = run_eval.set_files(question_set)
    spec = json.loads(question_file.read_text(encoding="utf-8"))
    if (spec.get("reference_date"), spec.get("freeze")) != (REFERENCE_DATE_3_5, FREEZE_3_5):
        problems.append(f"the question file names {spec.get('reference_date')} and {spec.get('freeze')}, "
                        f"not the contract's {REFERENCE_DATE_3_5} and {FREEZE_3_5}")
    for method, (meta, _) in runs.items():
        if (meta.get("reference_date"), meta.get("company_set")) != (REFERENCE_DATE_3_5, COMPANY_SET_3_5):
            problems.append(f"{method}: ran with {meta.get('reference_date')} and {meta.get('company_set')}, "
                            f"not {REFERENCE_DATE_3_5} and {COMPANY_SET_3_5}")
    freeze = ROOT / FREEZE_3_5
    record = json.loads(freeze.read_text(encoding="utf-8")) if freeze.exists() else {}
    if record.get("commit") != PRODUCT_3_5:
        problems.append(f"the freeze record does not name the product P3 {PRODUCT_3_5[:7]}")
    missing = [path for path in EVALUATOR_PATHS_3_5 if path not in (record.get("evaluator_paths") or ())]
    if missing:
        problems.append(f"the freeze record does not cover the evaluator files {missing}")
    registered = question_file.parent / "preregistration.json"
    hashes = json.loads(registered.read_text(encoding="utf-8")).get("hashes", {}) if registered.exists() else {}
    for method, (meta, _) in runs.items():
        recorded = meta.get("contract") or {}
        for key in ("set_questions", "set_gold"):
            if not hashes.get(key) or recorded.get(key) != hashes[key]:
                problems.append(f"{method}: {key} is not the pre-registered one")
    return problems


def check_contract(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], finals: dict[str, dict[str, Any]],
                   questions: dict[str, dict[str, Any]], golds: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """What the strict judge also requires (Codex 3-1 first review 3; EVAL_CONTRACT_3-5 section 9); empty when all is there."""
    problems = []
    question_set = runs["crosscheck"][0].get("question_set")
    contract = contract_of(question_set)
    missing = [method for method in (METHODS_3_5 if contract == "3-5" else METHODS) if method not in runs]
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
        for method, (method_meta, _) in runs.items():  # every run's own commit (amendment P5)
            changed = run_eval.frozen_differences((method_meta.get("git") or {}).get("commit") or "HEAD",
                                                  freeze=run_eval.freeze_file(question_set))
            if changed:
                problems.append(f"{method}: the run's code differs from the freeze commit P: {changed}")
    if contract == "3-5":
        problems += check_fixed_3_5(runs, question_set)
        found35 = Counter(question.get("bundle") for question in questions.values())
        if found35 != Counter(COMPOSITION_3_5) or {question.get("author") for question in questions.values()} != {"template"}:
            problems.append(f"the questions are not the contract's 600 (family -> count): {dict(found35)}")
        policy = run_eval.review_policy(question_set)
        if not policy:
            problems.append("the question file names no review policy")
        else:
            problems += check_sampled_reviews(runs, finals, golds or {}, policy)
        record = run_eval.set_files(question_set)[1].parent / "gold_disagreements.json"
        items = json.loads(record.read_text(encoding="utf-8"))["items"] if record.exists() else None
        if items is None:
            problems.append("no gold disagreement record")
        else:
            open_items = [item["id"] for item in items if not item.get("decision") or not item.get("approved_by_user")]
            if open_items:
                problems.append(f"gold disagreements not decided and approved by the user: {open_items}")
        failures = [case["id"] for case in runs["crosscheck"][1] if case.get("model_error")]
        if len(failures) > INFRASTRUCTURE_LIMIT_3_5 * len(runs["crosscheck"][1]):
            problems.append(f"model-server failures above 2% of the cross-check run ({len(failures)}): {failures}")
    elif meta.get("company_set") == "sealed-3-1":
        found: dict[str, Counter] = {}
        for question in questions.values():
            found.setdefault(question.get("bundle"), Counter())[question.get("author")] += 1
        expected = {bundle: Counter(authors) for bundle, authors in COMPOSITION_3_1.items()}
        if found != expected:
            problems.append(f"the questions are not the contract's 36 (bundle -> authors): {found}")
    return problems


def wrong_direction(case: dict[str, Any], gold: dict[str, Any], failure_kind: str | None = None) -> str:
    """EVAL_CONTRACT_3-5 section 6.2: "조심한 방향" only when every value is right and the shown status is the more
    careful 확인 필요 where the gold is 비교 가능 or 값 확인; any other wrong figure is "위험한 방향". A text the
    human review failed for a figure ("수치") is never the careful direction (Codex 3-5 review 3)."""
    answer = shown_answer(case) or {}
    score = case["score"]
    careful = (failure_kind != "수치" and answer.get("status") == "확인 필요"
               and gold.get("expected_status") in ("비교 가능", "값 확인")
               and score.get("numbers_ok") is True and score.get("basis_ok") is not False and not score.get("ungrounded"))
    return "조심한 방향" if careful else "위험한 방향"


def cluster_of(question: dict[str, Any]) -> str:
    expected = question["expected"]
    if "corp_code" not in expected or "account" not in expected:
        return "-"
    return f"{expected['corp_code']}/{expected.get('fs_div', 'CFS+OFS')}/{expected['account']}"


def template_report(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], outcomes: dict[str, dict[str, str]],
                    questions: dict[str, dict[str, Any]], golds: dict[str, dict[str, Any]],
                    finals: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """The 3-5 tables (contract sections 4.2, 5.3, 6.2, 9): by family, by group, the two directions of a wrong
    figure, the clusters with a wrong figure, and the 95% upper bound when there is none."""
    def table_by(key) -> dict[str, dict[str, dict[str, int]]]:
        found: dict[str, dict[str, dict[str, int]]] = {}
        for mode, result in outcomes.items():
            for item, cell in result.items():
                for group in key(questions[item]):
                    found.setdefault(mode, {}).setdefault(group, Counter())[cell] += 1
        return {mode: {group: dict(counter) for group, counter in sorted(groups.items())} for mode, groups in found.items()}

    def groups(question: dict[str, Any]) -> list[str]:
        choice = question.get("template") or {}
        return (list(question.get("tags", [])) + [name for name, key in (("별칭", "alias"), ("상대 연도", "relative_year"),
                                                                       ("계정 동의어", "synonym"), ("연결 명시", "explicit_basis"))
                                                  if choice.get(key)] or ["(표시 없음)"])

    cross = {case["id"]: case for case in runs["crosscheck"][1]}
    kinds = {mode: {entry["id"]: entry.get("failure_kind") for entry in ((finals or {}).get(mode) or {}).get("per_case", [])}
             for mode in outcomes}
    wrong = {mode: {item: wrong_direction(next(case for case in runs[mode][1] if case["id"] == item), golds[item],
                                          kinds[mode].get(item))
                    for item, cell in result.items() if cell == "잘못된 수치 답"} for mode, result in outcomes.items()}
    answered = [item for item, case in cross.items() if (shown_answer(case) or {}).get("status") in ANSWER_STATUSES]
    clusters = sorted({cluster_of(questions[item]) for item in wrong.get("crosscheck", {})})
    cells = {json.dumps([questions[item]["expected"].get(key) for key in ("corp_code", "fs_div", "account", "period",
                                                                           "current", "base")], sort_keys=True)
             for item in answered}
    bound = round(1 - 0.05 ** (1 / len(answered)), 5) if answered and not wrong.get("crosscheck") else None
    return {"by_family": table_by(lambda question: [question["bundle"]]), "by_group": table_by(groups),
            "wrong_figure_directions": wrong, "clusters_with_wrong_figures": clusters,
            "clusters_total": len({cluster_of(question) for question in questions.values()} - {"-"}),
            "figure_answers": len(answered), "distinct_cells_answered": len(cells),
            # section 9 (Codex 3-5 review 5): a reference figure assuming independent trials, which these are not
            "upper_bound_95": bound, "upper_bound_note": "독립 시행을 가정한 참고 계산"}


def judge(runs: dict[str, tuple[dict[str, Any], list[dict[str, Any]]]], finals: dict[str, dict[str, Any]] | None = None,
          exploratory: bool = False) -> dict[str, Any]:
    finals = finals or {}
    meta = runs["crosscheck"][0]
    with using_company_set(meta.get("company_set", "development")):
        questions, golds = run_eval.load_questions(meta.get("question_set", "dev"))
        by_id = {question["id"]: question for question in questions}
        problems = check_runs(runs, list(by_id))
        if not exploratory and not problems:
            problems += check_contract(runs, finals, by_id, golds)
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
    if contract_of(meta.get("question_set")) == "3-5":
        traps = [item for item, question in by_id.items() if str(question.get("bundle", "")).startswith("B")]
        trap_rate = sum(product[item] in ("맞는 거절", "맞는 되묻기") for item in traps) / len(traps) if traps else None
        checks = {
            "잘못된 수치 답 0": {"value": len(table["crosscheck"]["잘못된 수치 답"]), "met": not table["crosscheck"]["잘못된 수치 답"]},
            "해결률 ≥ 80%": {"value": solved_rate, "met": None if solved_rate is None else solved_rate >= CRITERIA_3_5["solved_rate"]},
            "함정 처리 ≥ 90%": {"value": trap_rate, "met": None if trap_rate is None else trap_rate >= CRITERIA_3_5["trap_rate"]},
            "근거 없는 숫자 0": {"value": ungrounded, "met": not any(ungrounded.values())},
        }
        report.update(template_report(runs, outcomes, by_id, golds, finals))
    else:
        checks = {
            "잘못된 수치 답 0": {"value": len(table["crosscheck"]["잘못된 수치 답"]), "met": not table["crosscheck"]["잘못된 수치 답"]},
            "해결률 ≥ 70%": {"value": solved_rate, "met": solved_rate is not None and solved_rate >= CRITERIA["solved_rate"]},
            "비용 ≤ 25%": {"value": cost_rate, "met": cost_rate is not None and cost_rate <= CRITERIA["cost_rate"]},
            "범위 밖·모호 ≥ 75%": {"value": scope_rate,
                               "met": None if scope_rate is None else scope_rate >= CRITERIA["out_of_scope_rate"]},
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
