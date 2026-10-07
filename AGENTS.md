# Instructions for coding agents (Codex and others)

This repository is developed with Claude Code (see `CLAUDE.md`) and reviewed independently by other agents. When you work here:

- **Never print, log, copy, or commit the OpenDART API key.** It lives in `~/.config/opendart/api_key`. Do not open that file. Do not make OpenDART API requests; everything you need is in the local `cache/` directory.
- **Do not inspect data for the sealed evaluation companies** (NAVER 00266961, CJ제일제당 00635134, 이마트 00872984, LG에너지솔루션 01515323). The cache does not contain them; do not fetch them.
- During a review, **do not modify tracked files** unless the user asks. Write your findings as your answer (or to a file the user names).
- Explain to the user in Korean; code and code comments are in English. `*.ko.md` files are Korean.
- Useful commands (offline, no key needed):
  - `python3 -m unittest discover -s tests`
  - `python3 eval/build_gold.py --check`
  - `python3 scripts/check_trap_tests.py`
  - `python3 scripts/check_public_safety.py`
- Cache layout: `cache/<endpoint>/<id>.body` holds the raw response, `<id>.meta.json` its request parameters, status, fetch time, and SHA-256. Financial statements are under `cache/fnlttSinglAcntAll.json/`; match a file to a report through `params` in its `.meta.json`.
