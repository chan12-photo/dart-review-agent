"""Exploratory: does sampling the same model several times reveal misreadings? (not part of the scored evaluation)

For each question (dev + paraphrase), ask the model for its structured reading
N times at a temperature above 0, and record how many distinct readings come
back and whether each matches the correct reading.

    python eval/run_consistency.py gpt-oss:20b 3 0.7 eval/feasibility_2026-10-07/consistency [YYYY-MM-DD]

The optional last argument is the reference date of the reading prompt
(default: today). Since 3-0b each row also keeps the raw replies or errors
(review B8: the first run kept only the canonical readings).
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

import run_eval  # noqa: E402
from dart_review.crosscheck import READING_SCHEMA, ReadingError, canonical, model_to_reading, parse_model_reading, reading_messages  # noqa: E402
from dart_review.llm import DEFAULT_OPTIONS, ModelError, OllamaChat  # noqa: E402


def expected_key(question: dict) -> tuple | None:
    name, arguments = (run_eval.interpretation_calls(question) or [(None, None)])[0]
    action = question["expected"]["action"]
    if action == "clarify":
        return canonical("clarify", None, arguments["company"], question["expected"]["options"])
    return canonical("side_by_side" if action == "side_by_side" else "compare", arguments, arguments["company"])


def main(argv: list[str]) -> int:
    model, samples, temperature, out = argv[0], int(argv[1]), float(argv[2]), Path(argv[3])
    reference_date = date.fromisoformat(argv[4]) if len(argv) > 4 else date.today()
    if out.exists():
        print(f"{out} exists; not overwritten")
        return 2
    chat = OllamaChat(model, options={**DEFAULT_OPTIONS, "temperature": temperature})
    identity = chat.prepare()
    rows = []
    for question_set in ("dev", "paraphrase"):
        questions, _ = run_eval.load_questions(question_set)
        for question in questions:
            expected, keys, raw = expected_key(question), [], []
            for _ in range(samples):
                reply = None
                try:
                    reply = chat.chat(reading_messages(question["question"], reference_date), schema=READING_SCHEMA)
                    reading = model_to_reading(parse_model_reading(reply.content))
                    keys.append(canonical(reading.kind, reading.arguments, reading.company, reading.options))
                    raw.append({"content": reply.content, "error": None})
                except (ReadingError, ModelError) as exc:
                    keys.append(None)
                    raw.append({"content": reply.content if reply else None, "error": f"{type(exc).__name__}: {exc}"})
            rows.append({"id": question["id"], "distinct": len({json.dumps(key) for key in keys}),
                         "correct": [key == expected for key in keys], "readings": [json.dumps(key, ensure_ascii=False) for key in keys],
                         "raw": raw})
    summary = {"model": identity, "samples": samples, "temperature": temperature, "questions": len(rows),
               "reference_date": reference_date.isoformat(),
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
