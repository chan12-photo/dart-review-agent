"""Build demo/ from the local cache and the recorded cross-check run (needs the cache; never the key).

1. Replays the five demo questions against the full cache, recording every
   OpenDART response the answers read (including restatement probes).
2. Writes those responses to demo/opendart/, keeping only the rows of the six
   target accounts (by standard id or known name; see dart_review/accounts.py).
3. Writes the model's recorded readings (from a cross-check run) to
   demo/model_replies.json, with the prompt version, the reference date of
   that run, and the SHA-256 of the messages and of the schema.
4. Checks that the demo built from the trimmed copies gives exactly the
   answers recorded in that run, and refuses to finish otherwise.

    python scripts/build_demo_fixtures.py eval/3-0b_2026-10-08/crosscheck_dev

The run must have used the current reading prompt and schema (its run.json
contract hashes are compared with the code).
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dart_review.accounts import ACCOUNTS, normalize_name  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from datetime import date  # noqa: E402

from dart_review.crosscheck import READING_PROMPT_VERSION, READING_SCHEMA  # noqa: E402
from dart_review.demo import DEMO_DIR, DEMO_QUESTIONS, ReplayChat, answer, messages_sha256, run_demo  # noqa: E402

sys.path.insert(0, str(ROOT / "eval"))
import run_eval  # noqa: E402

CACHE = ROOT / "cache"
TARGET_IDS = {account.account_id for account in ACCOUNTS.values()}
TARGET_NAMES = {normalize_name(name) for account in ACCOUNTS.values() for name in account.names}


class RecordingClient:
    def __init__(self, client: DartClient):
        self.client, self.requests = client, []

    @property
    def network_requests(self) -> int:
        return self.client.network_requests

    def financial_statements(self, corp_code: str, year: int, report_code: str, fs_div: str):
        self.requests.append((corp_code, year, report_code, fs_div))
        return self.client.financial_statements(corp_code, year, report_code, fs_div)


def keep(row: dict[str, Any]) -> bool:
    return row.get("account_id") in TARGET_IDS or normalize_name(row.get("account_nm", "")) in TARGET_NAMES


def main(argv: list[str]) -> int:
    if not CACHE.exists():
        print("no cache: run scripts/fetch_dev_cache.py first")
        return 2
    run_dir = Path(argv[0]) if argv else None
    if run_dir is None or not (run_dir / "run.json").exists():
        print("pass the folder of a crosscheck run made with the current prompt (run.json, cases.jsonl)")
        return 2
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    current = run_eval.contract_hashes()
    if meta.get("prompt_version") != READING_PROMPT_VERSION or any(
            meta["contract"].get(key) != current[key] for key in ("reading_prompt", "reading_schema")):
        raise SystemExit(f"{run_dir} was not made with the current reading prompt and schema")
    reference_date = date.fromisoformat(meta["reference_date"])
    run_file = run_dir / "cases.jsonl"
    recorded = {}
    for line in run_file.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if case["question"] in DEMO_QUESTIONS:
            request = case["requests"][0]
            recorded[case["question"]] = {"messages_sha256": messages_sha256(request["request"]["messages"]),
                                          "schema_sha256": messages_sha256(READING_SCHEMA),
                                          "content": request["response"]["message"]["content"],
                                          "answer": case["answer"]}
    missing = [question for question in DEMO_QUESTIONS if question not in recorded]
    if missing:
        raise SystemExit(f"no recorded run for {missing}")
    replies = {question: {key: value for key, value in item.items() if key != "answer"} for question, item in recorded.items()}

    def no_key() -> str:
        raise RuntimeError("must not need the key")

    full = RecordingClient(DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True))
    chat = ReplayChat(replies)
    from_cache = [answer(question, full, chat, reference_date) for question in DEMO_QUESTIONS]
    for item in from_cache:
        if item["answer"] != recorded[item["question"]]["answer"]:
            raise SystemExit(f"the full cache no longer reproduces the recorded answer: {item['question']}")

    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR / "opendart", ignore_errors=True)
    fixtures = ResponseCache(DEMO_DIR / "opendart")
    source = ResponseCache(CACHE)
    kept = total = 0
    for corp_code, year, report_code, fs_div in sorted(set(full.requests)):
        params = {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": report_code, "fs_div": fs_div}
        entry = source.get("fnlttSinglAcntAll.json", params)
        data = json.loads(entry.body)
        rows = data.get("list", [])
        total += len(rows)
        if rows:
            data["list"] = [row for row in rows if keep(row)]
            kept += len(data["list"])
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        fixtures.put("fnlttSinglAcntAll.json", params, body, entry.status, entry.message, entry.fetched_at)
    (DEMO_DIR / "model_replies.json").write_text(
        json.dumps({"source": str(run_file.resolve().relative_to(ROOT)), "prompt_version": READING_PROMPT_VERSION,
                    "reference_date": reference_date.isoformat(), "replies": replies}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    results, client = run_demo()
    for item in results:
        if item["answer"] != recorded[item["question"]]["answer"]:
            raise SystemExit(f"the trimmed fixtures change the answer: {item['question']}")
    print(f"{len(set(full.requests))} responses, rows kept {kept} of {total}; "
          f"demo answers identical to the recorded run; network requests {client.network_requests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
