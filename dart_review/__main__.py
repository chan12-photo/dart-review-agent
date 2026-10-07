"""Command line entry point.

    python -m dart_review demo   # replay demo: no OpenDART key, no model server, no network
"""

from __future__ import annotations

import argparse
import sys

from .demo import run_demo


def demo() -> int:
    results, client = run_demo()
    for index, item in enumerate(results, 1):
        print(f"# {index}. {item['question']}\n")
        if item["report"]:
            print(item["report"])
        else:
            print("(답을 내지 않음: " + ("근거 없는 숫자 " + str(item["withheld"]) if item["withheld"] else "도구 결과 없음") + ")\n")
        readings = item["readings"] or {}
        print(f"_해석 대조: {readings.get('used')}_\n")
    print(f"---\n재생 데모: 질문 {len(results)}개, OpenDART 네트워크 요청 {client.network_requests}회 (저장된 응답과 기록된 모델 해석을 재생)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m dart_review", description="공시 재무 비교 도구")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("demo", help="대표 질문 5개를 저장된 데이터로 재생한다 (키·모델·네트워크 불필요)")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo()
    return 2


if __name__ == "__main__":
    sys.exit(main())
