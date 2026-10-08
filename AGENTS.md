# Instructions for coding agents (Codex and others)

This repository is developed with Claude Code (see `CLAUDE.md`) and reviewed independently by other agents. When you work here:

- **Never print, log, copy, or commit the OpenDART API key.** It lives in `~/.config/opendart/api_key`. Do not open that file. Do not make OpenDART API requests; everything you need is in the local `cache/` directory.
- The sealed 3-1 evaluation (NAVER 00266961, CJ제일제당 00635134, 이마트 00872984, LG에너지솔루션 01515323) is finished; its result is in `eval/sealed_3-1/REPORT.md`. Do not re-run, tune on, or re-score its questions, and do not fetch new data.
- During a review, **do not modify tracked files** unless the user asks. Write your findings as your answer (or to a file the user names).
- Explain to the user in Korean; code and code comments are in English. `*.ko.md` files are Korean.
- Useful commands (offline, no key needed):
  - `python3 -m unittest discover -s tests`
  - `python3 -m dart_review demo` (replay demo from demo/: no key, no model server, no network)
  - `python3 eval/build_gold.py --check`
  - `python3 scripts/check_trap_tests.py`
  - `python3 eval/finalize.py <run folder>` (final scores after the human review in `human_review.json`)
  - `python3 eval/run_eval.py --mode rules` or `--mode baseline` (no model; the oracle, full, agent, and crosscheck modes call a local Ollama model, which reviewers should not do)
  - `python3 -m dart_review ask "질문" --no-model --cache demo/opendart --offline` (the CLI in its explicit rules-only mode, on the demo data)
  - `python3 scripts/build_account_vocabulary.py --check` (the committed account-name vocabulary still matches the cache)
  - `python3 -m unittest tests.test_replay_regression` (replays the saved baseline and crosscheck runs with their recorded model replies; any changed answer fails)
  - `DART_API_KEY_FILE=/nonexistent python3 scripts/check_public_safety.py` (by default the scan reads the local key file to look for its value; pointing it at a missing file skips that part, so the key file is never opened)
- Current product and policy: `docs/EVAL_DESIGN.ko.md` section 11.1 (cross-check, one-reader policy, unsupported accounts, reference date). The latest measurement is the sealed evaluation in `eval/sealed_3-1/REPORT.md`; earlier runs stay unchanged under `eval/feasibility_2026-10-07/`, `eval/3-0b_2026-10-08/`, and the other dated folders.
- Cache layout: `cache/<endpoint>/<id>.body` holds the raw response, `<id>.meta.json` its request parameters, status, fetch time, and SHA-256. Financial statements are under `cache/fnlttSinglAcntAll.json/`; match a file to a report through `params` in its `.meta.json`.
