"""D4 official result (contract 7판 5절, step ⑨): one run folder's saved reports, scored with a person's verdicts.

    python eval/d4_eval/official_d4.py --run <run folder> --judgments <folder> [--readers rules ai] [--out <official.json>]

For each call of the run (eval/d4_eval/run_d4.py: every document of eval/d4_eval/documents.json, its text PDF and
its three synthetic scans, for each reader of the run), the saved report ``<run>/reports/<name>.json`` is:
- scored by the frozen scorer (``eval/d4_score.score``, the same function as its command) against the gold with the
  confirmed mapping (renumbered by the scan's page map for a scan), with the person's verdicts on cells outside the
  gold from ``<judgments>/<name>.extras.json`` (contract 4.5) when that file exists;
- checked by the position check (``position_check.check``, contract 7판 4.6) with the registered places
  (``eval/d4_eval/duplicate_places.json``) and the person's verdicts from ``<judgments>/<name>.position.json``.
A verdict file that exists is an object naming the report's SHA-256 and who judged, also when it holds no verdict;
the tools refuse a file of another report or another shape ("null" too). The verdict files of each run folder have
their own folder (their names are the same in every run folder); a file there that this aggregation does not read
(another name, or another reader's) is listed (``judgment_files_not_read``).

Per call: ``S1_official`` = the scorer's S1 + the position check's ``S1_position``; L1, S2, G1 as scored;
the cells and places still waiting for a person (``extras_to_judge``, and ``position_places`` with "needs_verdict");
``official_ready`` = the scorer's ``official_ready`` and the position check's ``position_ready``, and the run let the
call be official. The run lets a call be official only when its record is whole and agrees with itself (Codex
seventh re-check 1, eighth review 1), else no call of the folder is official:
- ``run.json`` is the finished record (``finished_at``) of a run started with a passed preflight (``preflight``) on
  this document list (``documents_sha256``), of readers in the registered order (rules before ai, each once);
- ``run_log.jsonl`` lists exactly the planned calls, each once, in the planned order (``n`` = 1, 2, ...), each with a
  whole-number exit;
- ``calls`` is the number of planned calls, ``failed`` names exactly the logged calls whose exit was not 0 (with that
  exit, each once), and ``succeeded`` is the rest;
and then the call itself exited 0. A report that a failed call left behind (the scorer saves the report before it
scores) is never official; its numbers are shown as provisional. A call without a saved report, or whose report or
verdict file the tools refuse (a file of another shape too), is not official.

Per reader and bundle (3.1: the text PDFs; 3.3: the 30 synthetic scans) the sums, and the verdict (contract 5):
- "met" / "not met" only when every call of the bundle is ``official_ready``: 3.1 needs S1_official = L1 = S2 = 0,
  3.3 needs S1_official = 0;
- otherwise "not official", with the calls that keep it so and why (the sums are shown as provisional).
The product's verdict is the AI reader's (contract 5). Nothing is written into the run folder; ``--out`` must not
exist. One run folder is read per call of this tool: calls of two folders are never mixed. After a model server
failure a reader runs again, whole, in a new folder (contract 7); its official result is that folder's, taken with
``--readers`` (docs/D4_RUN_PROCEDURE.ko.md ⑨).
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "eval"), str(ROOT / "eval" / "d4_eval")]

from eval.d4_score import score  # noqa: E402
import position_check  # noqa: E402
from document_list import PROFILES, _same_place, check_document_list, inside, registered_count  # noqa: E402

DOCUMENTS = ROOT / "eval" / "d4_eval" / "documents.json"
READERS = ("rules", "ai")  # the registered order (eval/d4_eval/run_d4.py)
PLACES = ROOT / "eval" / "d4_eval" / "duplicate_places.json"
VARIANTS = ("text", "normal", "tilt", "blur")
BUNDLES = {"3.1": ("text",), "3.3": ("normal", "tilt", "blur")}
CRITERIA = {"3.1": ("S1_official", "L1", "S2"), "3.3": ("S1_official",)}
SUMS = ("gold_cells", "correct", "S1", "S1_position", "S1_official", "L1", "S2", "G1", "flagged", "product_cells",
        "not_in_gold", "extras_judged", "position_wrong", "places", "sums_checked", "statements_with_uncertain_sums",
        "statements_without_sums", "statements_sums_not_checked_by_kind", "mapping_decisions")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def run_gate(run: Path, record: dict, names: list[str]) -> dict[str, str | None]:
    """Per call name, why the run does not let it be official (None: the run lets it be). ``names`` are the planned
    calls of the run's readers in the planned order."""
    whole = []
    if not record.get("finished_at"):
        whole.append("the run did not finish (run.json has no finished_at)")
    if not isinstance(record.get("preflight"), dict) or not record["preflight"].get("sha256"):
        whole.append("run.json records no passed preflight")
    if record.get("documents_sha256") != _sha256(DOCUMENTS):
        whole.append("the run read another document list (documents_sha256)")
    readers = record.get("readers")
    if not isinstance(readers, list) or not readers or readers != [r for r in READERS if r in readers]:
        whole.append(f"run.json readers {readers!r} are not readers in the registered order, each once")
    log = run / "run_log.jsonl"
    try:
        logged = [json.loads(line) for line in (log.read_text(encoding="utf-8").splitlines() if log.exists() else [])]
        if not all(isinstance(item, dict) for item in logged):
            raise ValueError
    except ValueError:
        whole.append("run_log.jsonl cannot be read")
        logged = []
    exits = {}
    if [item.get("name") for item in logged] != names:
        whole.append(f"run_log.jsonl does not list the planned calls once each in order ({len(logged)} entries, "
                     f"{len(names)} planned)")
    elif [item.get("n") for item in logged] != list(range(1, len(names) + 1)):
        whole.append("run_log.jsonl numbers its entries out of order")
    elif not all(_whole(item.get("exit")) for item in logged):
        whole.append("run_log.jsonl has an entry without a whole-number exit")
    else:
        exits = {item["name"]: item["exit"] for item in logged}
    failed = record.get("failed")
    if not isinstance(failed, list) or not all(isinstance(f, dict) and isinstance(f.get("name"), str) for f in failed):
        whole.append("run.json has no list of failed calls")
        failed = []
    listed = {f["name"]: f.get("exit") for f in failed}
    if len(listed) != len(failed):
        whole.append("run.json lists a failed call twice")
    if exits and listed != {name: code for name, code in exits.items() if code != 0}:
        whole.append("run.json's failed calls are not the logged calls that did not exit 0")
    if record.get("calls") != len(names) or record.get("succeeded") != len(names) - len(failed):
        whole.append(f"run.json does not add up: calls {record.get('calls')}, succeeded {record.get('succeeded')}, "
                     f"failed {len(failed)}, {len(names)} calls planned")
    gate = {}
    for name in names:
        why = list(whole)
        if exits.get(name, 0) != 0:
            why.append(f"the call exited {exits[name]}")
        if name in listed:
            why.append("run.json lists the call as failed")
        gate[name] = "; ".join(why) or None
    return gate


def call(document: dict, variant: str, reader: str, run: Path, judgments: Path, registered: dict) -> dict:
    """One call's official numbers, or why it is not official."""
    name = f"{document['key']}.{variant}.{reader}"
    entry = {"name": name, "key": document["key"], "company": document.get("company"), "variant": variant, "reader": reader}
    report_path = run / "reports" / f"{name}.json"
    if not report_path.exists():
        return entry | {"official_ready": False, "why": "no saved report (the call failed or did not run)"}
    page_map = _json(ROOT / document["scans"][variant]["map"]) if variant != "text" else None
    report_sha256 = _sha256(report_path)
    extras_path, position_path = judgments / f"{name}.extras.json", judgments / f"{name}.position.json"
    mapping = json.loads((ROOT / document["mapping"]).read_text(encoding="utf-8"))
    entry |= {"report_sha256": report_sha256, "mapping_decisions": len(mapping.get("decisions") or {}),
              "judgments": {p.name: _sha256(p) for p in (extras_path, position_path) if p.exists()}}
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("the saved report is not a report")
        # A verdict file is read when it exists, by its path, not by what it holds ("null" in a file is a file: Codex
        # ninth review 1). It is an object naming this report and who judged, also with no verdict, and its
        # "verdicts" is an object ({} when empty; a list, string, false, or null is refused: eighth review 2)
        loaded = {}
        for path in (extras_path, position_path):
            if not path.exists():
                loaded[path] = None
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("verdicts", {}), dict):
                raise ValueError(f"{path.name} is not {{\"report_sha256\", \"judged_by\", \"verdicts\": {{id: verdict}}}}")
            if data.get("report_sha256") != report_sha256:
                raise ValueError(f"{path.name} is for another report (report_sha256 differs)")
            if not isinstance(data.get("judged_by"), str) or not data["judged_by"].strip():
                raise ValueError(f"{path.name} does not say who judged (judged_by)")
            loaded[path] = data
        extras, verdicts = loaded[extras_path] or {}, loaded[position_path]
        gold = position_check._gold_for(document, page_map)
        scored_all = score(gold, report, extras, report_sha256)
        placed = position_check.check(registered, document, report, page_map, verdicts, report_sha256)
    except ValueError as exc:
        return entry | {"official_ready": False, "why": f"refused: {exc}"}
    except (TypeError, AttributeError, KeyError) as exc:  # a file of another shape: refused, never scored as it is
        return entry | {"official_ready": False, "why": f"refused: a file of another shape ({type(exc).__name__}: {exc})"}
    scored = scored_all["totals"]
    status = scored["status"]
    # what a person still judges (contract 4.5): unmarked cells outside the gold without a verdict, by their report id
    to_judge = [{k: x[k] for k in ("id", "statement", "page", "label", "period", "printed", "value")}
                for part in scored_all["statements"] + scored_all["product_statements_not_in_gold"]
                for x in part["extras"] if not x["flagged"] and x["verdict"] is None]
    entry |= {key: scored[key] for key in ("gold_cells", "correct", "S1", "L1", "S2", "G1", "flagged", "product_cells",
                                            "not_in_gold", "unjudged_extras", "sums_checked",
                                            "statements_with_uncertain_sums", "statements_without_sums",
                                            "statements_sums_not_checked_by_kind")}
    entry |= {"S1_parts": scored["S1_parts"], "extras_judged": len((extras.get("verdicts") or {})),
              "places": placed["totals"]["places"], "position_wrong": placed["totals"]["position_wrong"],
              "S1_position": placed["totals"]["S1_position"], "needs_verdict": placed["totals"]["needs_verdict"],
              "position_places": [p for p in placed["places"] if p["status"] not in ("in_order", "not_pairable_no_swap")],
              "extras_to_judge": to_judge}
    entry["S1_official"] = entry["S1"] + entry["S1_position"]
    entry["status"] = status | {"position_ready": placed["totals"]["position_ready"]}
    entry["official_ready"] = bool(status["official_ready"] and placed["totals"]["position_ready"])
    if not entry["official_ready"]:
        why = [k for k in ("mapping_confirmed", "extras_judged", "scorable", "source_verified", "report_saved",
                           "position_ready") if not entry["status"][k]]
        entry["why"] = "not yet: " + ", ".join(why)
    return entry


def bundle(entries: list[dict], criteria: tuple[str, ...], expected_calls: int | None = None) -> dict:
    sums = {key: sum(e.get(key) or 0 for e in entries) for key in SUMS}
    waiting = [{"name": e["name"], "why": e["why"]} for e in entries if not e["official_ready"]]
    if not entries:
        waiting = [{"name": None, "why": "no call in the bundle"}]
    if expected_calls is None or len(entries) != expected_calls or len({e["name"] for e in entries}) != len(entries):
        # a bundle is judged on all of its registered calls, each once (Codex D5 review 1)
        waiting = waiting + [{"name": None, "why": f"the bundle has {len(entries)} calls, not the {expected_calls} of the "
                                                   "registered documents"}]
    result = {"calls": len(entries), "documents": len({e["key"] for e in entries}), "sums": sums,
              "A1_flagged_share": round(sums["flagged"] / sums["product_cells"], 4) if sums["product_cells"] else None,
              "A2_covered_share": round(sums["correct"] / sums["gold_cells"], 4) if sums["gold_cells"] else None,
              "criteria": {key: 0 for key in criteria}}
    if waiting:
        return result | {"verdict": "not official", "provisional": True, "not_official": waiting}
    return result | {"verdict": "met" if all(sums[key] == 0 for key in criteria) else "not met", "provisional": False}


def official(run: Path, judgments: Path, documents: dict, registered: dict, readers: list[str] | None = None,
             expected: int | None = None, d4_legacy: bool = False, root: Path | None = ROOT) -> dict:
    """``expected``: N from outside the list (``registered_count``). ``root``: the repository every gold, mapping,
    and map path of the list is inside (a test gives its own folder, or None for absolute fixture paths)."""
    # the whole registered sample, each document once: never a verdict on part of it (Codex D5 review 1, re-check 1)
    count = check_document_list(documents, expected, d4_legacy=d4_legacy, root=root)
    record = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"{run / 'run.json'} is not a run record")
    ran = [r for r in READERS if r in record["readers"]] if isinstance(record.get("readers"), list) else []
    if readers is not None and not set(readers) <= set(ran):
        raise ValueError(f"the run folder ran {ran}, not {readers}")
    names = [f"{d['key']}.{v}.{r}" for r in ran for d in documents["documents"] for v in VARIANTS]
    gate = run_gate(run, record, names)
    chosen = [r for r in READERS if r in (readers if readers is not None else ran)]  # each reader once
    entries = []
    for reader in chosen:
        for document in documents["documents"]:
            for variant in VARIANTS:
                entry = call(document, variant, reader, run, judgments, registered)
                if gate[entry["name"]]:
                    reason = f"run: {gate[entry['name']]}"
                    entry |= {"official_ready": False, "why": reason + (f"; {entry['why']}" if entry.get("why") else "")}
                entries.append(entry)
    result = {}
    for reader in chosen:
        mine = [e for e in entries if e["reader"] == reader]
        result[reader] = {name: bundle([e for e in mine if e["variant"] in variants], CRITERIA[name], count * len(variants))
                          for name, variants in BUNDLES.items()}
    # the files of the judgments folder this aggregation did not read: a misspelt name, or the verdicts of a reader
    # not taken here (a file that is not read never counts; its call waits for its verdicts)
    known = {f"{e['name']}.{kind}.json" for e in entries for kind in ("extras", "position")}
    unused = sorted(p.name for p in judgments.glob("*") if p.name not in known) if judgments.is_dir() else []
    return {"run_folder": run.name, "judgment_files_not_read": unused,
            "run": {key: record.get(key) for key in ("commit", "started_at", "finished_at", "preflight", "readers",
                                                     "calls", "succeeded", "failed")},
            "documents_sha256": _sha256(DOCUMENTS), "places_sha256": _sha256(PLACES),
            # N from outside the list; D4's records keep their own form (Codex D5 third review 3)
            **({} if d4_legacy else {"expected_documents": count}), "product_reader": "ai",
            "readers": result, "calls": entries}


def main(argv: list[str] | None = None) -> int:
    global DOCUMENTS, PLACES
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--run", type=Path, required=True, help="a run folder of eval/d4_eval/run_d4.py")
    parser.add_argument("--judgments", type=Path, required=True, help="the folder of the person's verdict files")
    parser.add_argument("--readers", nargs="+", choices=("rules", "ai"),
                        help="only these readers of the folder (after a reader ran again in a new folder)")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--documents", type=Path, default=DOCUMENTS, help="the registered document list (default: D4's)")
    parser.add_argument("--places", type=Path, default=PLACES, help="the registered places (default: D4's)")
    args = parser.parse_args(argv)
    DOCUMENTS, PLACES = args.documents, args.places
    if args.out and args.out.exists():
        parser.error(f"{args.out} exists")
    try:
        profile, count = registered_count(DOCUMENTS, ROOT)
        own = PROFILES[profile]["places"]
        if not _same_place(PLACES, ROOT / own) or not inside(ROOT, own):
            raise ValueError(f"the places of the {profile} list are {PROFILES[profile]['places']}, not {PLACES}")
        result = official(args.run, args.judgments, json.loads(DOCUMENTS.read_text(encoding="utf-8")),
                          json.loads(PLACES.read_text(encoding="utf-8")), args.readers, count,
                          d4_legacy=profile == "d4")
    except ValueError as exc:
        parser.error(str(exc))
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if result["judgment_files_not_read"]:
        print(f"judgment files not read by this aggregation: {', '.join(result['judgment_files_not_read'])}")
    for reader, bundles in result["readers"].items():
        for name, part in bundles.items():
            sums = part["sums"]
            print(f"{reader} {name}: {part['verdict']} (S1_official {sums['S1_official']}, L1 {sums['L1']}, "
                  f"S2 {sums['S2']}; {part['calls']} calls" + (f", {len(part['not_official'])} not official" if
                                                                 part.get("not_official") else "") + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
