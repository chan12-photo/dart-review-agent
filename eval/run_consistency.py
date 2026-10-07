"""Exploratory: does sampling the same model several times reveal misreadings? (not part of the scored evaluation)

For each question (dev + paraphrase), ask the model for its structured reading
N times at a temperature above 0, and record how many distinct readings come
back and whether each matches the correct reading.

    python eval/run_consistency.py gpt-oss:20b 3 0.7 eval/feasibility_2026-10-07/consistency
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import run_eval  # noqa: E402
from dart_review.crosscheck import READING_SCHEMA, READING_SYSTEM_PROMPT, ReadingError, canonical, model_to_reading, parse_model_reading  # noqa: E402
from dart_review.llm import DEFAULT_OPTIONS, ModelError, OllamaChat  # noqa: E402


def expected_key(question: dict) -> tuple | None:
    name, arguments = (run_eval.interpretation_calls(question) or [(None, None)])[0]
    action = question["expected"]["action"]
    if action == "clarify":
        return ("clarify",) + canonical("clarify", None, arguments["company"])[1:]
    return canonical("side_by_side" if action == "side_by_side" else "compare", arguments, arguments["company"])


def main(argv: list[str]) -> int:
    model, samples, temperature, out = argv[0], int(argv[1]), float(argv[2]), Path(argv[3])
    if out.exists():
        print(f"{out} exists; not overwritten")
        return 2
    chat = OllamaChat(model, options={**DEFAULT_OPTIONS, "temperature": temperature})
    identity = chat.prepare()
    rows = []
    for question_set in ("dev", "paraphrase"):
        questions, _ = run_eval.load_questions(question_set)
        for question in questions:
            expected, keys = expected_key(question), []
            for _ in range(samples):
                try:
                    reply = chat.chat([{"role": "system", "content": READING_SYSTEM_PROMPT},
                                       {"role": "user", "content": question["question"]}], schema=READING_SCHEMA)
                    reading = model_to_reading(parse_model_reading(reply.content))
                    keys.append(canonical(reading.kind, reading.arguments, reading.company))
                except (ReadingError, ModelError):
                    keys.append(None)
            rows.append({"id": question["id"], "distinct": len({json.dumps(key) for key in keys}),
                         "correct": [key == expected for key in keys], "readings": [json.dumps(key, ensure_ascii=False) for key in keys]})
    summary = {"model": identity, "samples": samples, "temperature": temperature, "questions": len(rows),
               "unstable_questions": [row["id"] for row in rows if row["distinct"] > 1],
               "wrong_samples": sum(row["correct"].count(False) for row in rows),
               "all_wrong_but_stable": [row["id"] for row in rows if row["distinct"] == 1 and not row["correct"][0]],
               "requests": chat.attempts}
    out.mkdir(parents=True)
    (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "model"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
