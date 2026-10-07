"""Check that the local Ollama accepts the evaluation's answer schema and tool format (2 requests).

Uses a made-up company and question unrelated to the evaluation set, so it
reveals nothing about the questions and its output is not a model score.

    python scripts/check_ollama.py gpt-oss:20b eval/feasibility_<date>/connection_check.json
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.answer import ANSWER_SCHEMA, AnswerFormatError, parse_answer  # noqa: E402
from dart_review.llm import ModelError, OllamaChat  # noqa: E402
from dart_review.tools import TOOL_SPECS  # noqa: E402

SCHEMA_PROMPT = [
    {"role": "system", "content": "정해진 JSON 형식으로만 답한다."},
    {"role": "user", "content": "가상의 회사 '가나다상사'에 대해 사용자가 '이익이 늘었어?'라고 물었다. 영업이익인지 당기순이익인지 "
                                "알 수 없으니 status는 '되묻기', company는 '가나다상사', account·change·change_pct·values는 비워(null, []) 두고, "
                                "answer와 clarifying_question에 되묻는 문장을 써라."},
]
TOOL_PROMPT = [
    {"role": "system", "content": "필요하면 도구를 부른다."},
    {"role": "user", "content": "가나다상사의 2025년 연간 연결 매출을 2024년 연간과 compare_values 도구로 비교해 줘."},
]


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    model, out = argv[0], Path(argv[1])
    if out.exists():
        print(f"{out} exists; not overwritten")
        return 2
    chat = OllamaChat(model)
    result: dict = {"identity": chat.prepare(), "checks": {}}
    try:
        reply = chat.chat(SCHEMA_PROMPT, schema=ANSWER_SCHEMA)
        try:
            parsed = parse_answer(reply.content).to_dict()
            result["checks"]["schema"] = {"ok": True, "parsed": parsed}
        except AnswerFormatError as exc:
            result["checks"]["schema"] = {"ok": False, "format_error": str(exc)}
    except ModelError as exc:
        result["checks"]["schema"] = {"ok": False, "model_error": str(exc)}
    result["checks"]["schema"]["exchange"] = chat.last_exchange
    try:
        reply = chat.chat(TOOL_PROMPT, tools=TOOL_SPECS)
        calls = reply.tool_calls
        shaped = [isinstance(call, dict) and isinstance(call.get("function"), dict) for call in calls]
        result["checks"]["tools"] = {"ok": bool(calls) and all(shaped), "tool_calls": calls}
    except ModelError as exc:
        result["checks"]["tools"] = {"ok": False, "model_error": str(exc)}
    result["checks"]["tools"]["exchange"] = chat.last_exchange
    result["attempts"], result["responses"] = chat.attempts, chat.responses
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({name: {key: value for key, value in check.items() if key != "exchange"}
                      for name, check in result["checks"].items()}, ensure_ascii=False, indent=1))
    return 0 if all(check["ok"] for check in result["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
