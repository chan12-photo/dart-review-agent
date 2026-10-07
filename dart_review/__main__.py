"""Command line entry point.

    python -m dart_review demo                      # replay demo: no key, no model server, no network
    python -m dart_review ask "질문"                 # cross-checked answer (local Ollama, OpenDART cache/key)
    python -m dart_review ask "질문" --no-model      # keyword rules only, marked as a single reading
    python -m dart_review ask "질문" --cache demo/opendart --offline   # try it on the demo data, no key
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .cache import ResponseCache
from .client import DartClient, DartError
from .demo import answer, run_demo
from .llm import ModelError, OllamaChat, Reply

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "gpt-oss:20b"


class NoModel:
    """Stands in for the model when --no-model is given: its reading is unusable, so the rules answer alone."""

    def chat(self, messages, **kwargs) -> Reply:
        return Reply("")


def show(item: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({key: value for key, value in item.items() if key != "seen"}, ensure_ascii=False, indent=1))
        return
    if item["report"]:
        print(item["report"])
    elif item["withheld"]:
        print(f"(답을 내보내지 않음: 도구 결과로 확인되지 않는 숫자 {item['withheld']})")
    else:
        errors = [result["error"] for result in item.get("seen", []) if isinstance(result, dict) and "error" in result]
        reason = errors[-1] if errors else "지원하는 회사·계정·연도인지 확인해 주세요"
        print(f"(답할 수 있는 해석이나 조회 결과가 없음: {reason})")
    readings = item["readings"] or {}
    print(f"_해석 대조: {readings.get('used')}_")


def demo() -> int:
    results, client = run_demo()
    for index, item in enumerate(results, 1):
        print(f"# {index}. {item['question']}\n")
        show(item, as_json=False)
        print()
    print(f"---\n재생 데모: 질문 {len(results)}개, OpenDART 네트워크 요청 {client.network_requests}회 (저장된 응답과 기록된 모델 해석을 재생)")
    return 0


def ask(args: argparse.Namespace) -> int:
    if not args.cache.exists():
        print(f"응답 캐시가 없습니다: {args.cache} (scripts/fetch_dev_cache.py로 받거나 --cache demo/opendart --offline으로 시험)")
        return 2
    client = DartClient(ResponseCache(args.cache), offline=args.offline)
    chat = NoModel() if args.no_model else OllamaChat(args.model)
    try:
        item = answer(args.question, client, chat)
    except ModelError as exc:
        print(f"로컬 모델에 묻지 못했습니다: {exc}\nOllama를 127.0.0.1:11434에서 켜거나, --no-model로 규칙 해석만 쓸 수 있습니다.")
        return 3
    except DartError as exc:
        print(f"OpenDART 조회에 실패했습니다: {exc}")
        return 4
    show(item, args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dart_review", description="공시 재무 비교 도구 (교차 확인형)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="대표 질문 5개를 저장된 데이터로 재생한다 (키·모델·네트워크 불필요)")
    asking = commands.add_parser("ask", help="질문 하나를 규칙과 모델이 각자 읽고, 같으면 답하고 다르면 되묻는다")
    asking.add_argument("question")
    asking.add_argument("--model", default=DEFAULT_MODEL, help=f"로컬 Ollama 모델 (기본 {DEFAULT_MODEL})")
    asking.add_argument("--no-model", action="store_true", help="모델 없이 규칙 해석만 쓴다 (한 가지 해석으로만 확인했다고 표시)")
    asking.add_argument("--cache", type=Path, default=ROOT / "cache", help="OpenDART 응답 캐시 폴더")
    asking.add_argument("--offline", action="store_true", help="캐시에 없는 보고서를 받지 않는다 (인증키 불필요)")
    asking.add_argument("--json", action="store_true", help="구조화된 답을 JSON으로 출력한다")
    args = parser.parse_args(argv)
    return demo() if args.command == "demo" else ask(args)


if __name__ == "__main__":
    sys.exit(main())
