# Working rules for this repository

- Explain progress, decisions, and questions to the user in Korean. Write code, comments, commit messages, and English documentation in English; files named `*.ko.md` are Korean.
- At the start of each session, read `docs/ROADMAP.ko.md` (current state and the first unfinished task) and `docs/SCOPE.ko.md`. Before starting a task, tell the user the recommended effort mode listed for it (중간 / 높음 / 엑스트라).
- One task per session where possible. At the end, update the task markers and the "현재 상태" section of the roadmap, then commit.
- Ask the user before pushing, creating or renaming GitHub repositories, changing visibility, or using the stored `gh` login.
- The OpenDART key lives only in `~/.config/opendart/api_key` (mode 600). Never print it, log it, write it into the repository, or put it in cache files or error messages. Check that no tracked file contains it before every commit.
- Raw API responses go to `cache/` (git-ignored) until their redistribution terms are confirmed.
- The four evaluation companies (NAVER, CJ제일제당, 이마트, LG에너지솔루션) are sealed: do not inspect their data during development.
- Report failures and ambiguous results as they are; do not change an evaluation's criteria after seeing its results. After any commit that adds files, verify from a fresh clone.
- Reusable parts (policy checks, run logging, replay, pre-registered evaluation, public-safety scan) come from the sibling repository `../ai_job_agent` (GitHub: `chan12-photo/local-agent-lab`).
