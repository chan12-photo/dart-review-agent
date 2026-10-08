"""Exploratory probe of the cross-check policy on questions outside the development sets (not scored).

Runs eval/probe_3-0b.json through the product path (dart_review.demo.answer:
cross-check, tool, renderer, final report check) with a local model, and
records for each question the rule and model readings next to the reading
expected before the run, the path used, what was shown, and the exact model
request and raw reply.

    python eval/run_probe.py gpt-oss:20b eval/3-0b_2026-10-08/probe
"""

from __future__ import annotations

import copy
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import run_eval  # noqa: E402
from dart_review.baseline import read  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.crosscheck import READING_PROMPT_VERSION, canonical  # noqa: E402
from dart_review.demo import answer  # noqa: E402
from dart_review.llm import OllamaChat  # noqa: E402

PROBE = ROOT / "eval" / "probe_3-0b.json"


def expected_key(expected: dict[str, Any]) -> tuple | None:
    arguments = {key: value for key, value in expected.items() if key != "kind"}
    return canonical(expected["kind"], arguments, expected["company"])


def reading_key(reading: dict[str, Any] | None) -> tuple | None:
    if not reading or reading.get("kind") in (None, "unreadable"):
        return None
    return canonical(reading["kind"], reading.get("arguments") or {}, reading.get("company"), reading.get("options", ()))


class Recorded:
    """Keeps every request and raw reply of the wrapped model client."""

    def __init__(self, inner: OllamaChat):
        self.inner, self.exchanges = inner, []

    def chat(self, messages, **kwargs):
        try:
            return self.inner.chat(messages, **kwargs)
        finally:
            self.exchanges.append(copy.deepcopy(self.inner.last_exchange))


def main(argv: list[str]) -> int:
    model, out = argv[0], Path(argv[1])
    if out.exists():
        print(f"{out} exists; not overwritten")
        return 2
    git = run_eval._git_state()
    if git["dirty"]:
        print("commit first: the probe must name the exact code it ran")
        return 2
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    reference_date = date.fromisoformat(probe["reference_date"])
    client = DartClient(ResponseCache(run_eval.CACHE), key_loader=run_eval.no_key, offline=True)
    ollama = OllamaChat(model)
    identity = ollama.prepare()
    out.mkdir(parents=True)
    meta = {"model": identity, "prompt_version": READING_PROMPT_VERSION, "reference_date": probe["reference_date"],
            "contract": run_eval.contract_hashes(), "probe_sha256": run_eval._sha256(PROBE.read_bytes()), "git": git,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "run.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    rows = []
    with (out / "cases.jsonl").open("w", encoding="utf-8") as handle:
        for item in probe["questions"]:
            recorded = Recorded(ollama)
            try:
                shown = answer(item["question"], client, recorded, reference_date)
                error = None
            except Exception as exc:  # a model or evaluator failure fails this question only, and is recorded
                shown, error = None, f"{type(exc).__name__}: {exc}"
            readings = (shown or {}).get("readings") or {}
            rule = read(item["question"])
            expected = expected_key(item["expected"])
            model_key = reading_key(readings.get("model"))
            rule_key = canonical(rule.kind, rule.arguments, rule.company, rule.options) if rule.kind != "unreadable" else None
            row = {"id": item["id"], "group": item["group"], "question": item["question"], "expected": item["expected"],
                   "rule_correct": rule_key == expected, "model_correct": model_key == expected,
                   "used": readings.get("used"), "status": ((shown or {}).get("answer") or {}).get("status"),
                   "withheld": (shown or {}).get("withheld"), "withheld_reason": (shown or {}).get("withheld_reason"),
                   "error": error}
            rows.append(row)
            handle.write(json.dumps({**row, "readings": readings, "answer": (shown or {}).get("answer"),
                                     "report": (shown or {}).get("report"), "seen": (shown or {}).get("seen"),
                                     "exchanges": recorded.exchanges}, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"{row['id']} {row['group']:<13} rule {'O' if row['rule_correct'] else 'X'} model {'O' if row['model_correct'] else 'X'}"
                  f"  used={row['used']}  status={row['status']}  {row['withheld_reason'] or ''}{row['error'] or ''}")
    summary = {"questions": len(rows), "rule_correct": sum(row["rule_correct"] for row in rows),
               "model_correct": sum(row["model_correct"] for row in rows),
               "by_path": {path: [row["id"] for row in rows if row["used"] == path] for path in sorted({str(row["used"]) for row in rows})},
               "errors": [row["id"] for row in rows if row["error"]], "network_requests": client.network_requests}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
