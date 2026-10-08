# dart-review-agent

**Status: work in progress (draft README, 2026-10-08).** Results below are from self-authored development questions; the sealed, pre-registered evaluation has not been run yet. Korean version: [README.ko.md](README.ko.md).

A local tool that answers questions like *"How much did Samsung Electronics' revenue grow in 2025?"* from OpenDART financial statements. It compares figures across periods only when the comparison is sound (same consolidated/separate basis, same period length, same currency, no unexplained restatement), and refuses or asks back otherwise. Every financial figure it shows comes from a verified tool result.

```text
$ python -m dart_review demo        # no API key, no model server, no network
## 삼성전자 매출액
**검증 상태:** 비교 가능
| 구분 | 기준 | 기간 | 금액(원) | 보고서 | 접수번호 |
| 비교 기간 | 연결 | 2025년 연간(1~12월) | 333,605,938,000,000 | 2025년 사업보고서 | 20260310002820 |
| 기준 기간 | 연결 | 2024년 연간(1~12월) | 300,870,903,000,000 | 2025년 사업보고서 | 20260310002820 |
**변화:** 32,735,035,000,000원 (10.88%, 증가)
```

## Why this is harder than it looks

The same OpenDART column means different things depending on the report and the statement. These were checked against 72 cached reports ([data notes](docs/DATA_NOTES.ko.md)):

- In quarterly income statements `thstrm` is the three months; in quarterly cash flow statements it is already year to date.
- In quarterly balance sheets the "prior period" column is the **prior year end**, not the same quarter of the prior year.
- Later reports **restate** earlier figures (Kakao, Celltrion): Kakao's Q3 2024 revenue change is −4.48% against the restated prior figure and −11.08% against the originally filed one.
- Account ids can be wrong: Kakao's 2023 quarterly revenue is tagged `ifrs-full_GrossProfit`.

The rules for all of these are code, tested on the real cache, and each trap test was shown to fail when its rule is replaced by a naive version (11 of 11 caught).

## How it works (cross-checked reading)

```text
question ──► keyword rules ──► reading A ─┐
         └─► local model   ──► reading B ─┤ same?  ── yes ─► tool (rules on OpenDART data) ─► code writes the answer ─► number check ─► answer
                                          └─ no ──► show both readings and ask which one was meant
```

- Two readers interpret the question separately: keyword rules and a local model (`gpt-oss:20b` via Ollama, one structured reading request with a reference date in the prompt). If they agree, code answers; if not, it asks back. Both were built by one author from one table of defaults, so their errors are not guaranteed to be independent.
- When only one reader produces a reading:
  - if the model's reading is missing, nothing is answered. The rules alone are not trusted with an answer; they confidently misread paraphrase p06.
  - if the rules cannot read the question and the model can (e.g. "last year's revenue" with no year, or the synonym "순익"), the answer starts with the model's reading in code-written words ("이렇게 이해했습니다: …"), so a misreading is visible.
  - `--no-model` is an explicit rules-only mode chosen by the user, and the answer says so.
- An account outside the six supported ones is refused, never read as a similar supported account. This includes names that contain a supported one, such as 유동자산 (current assets, not total assets) or 매출원가 (cost of sales, not revenue). A refusal is final only when both readers refuse.
- Every factual sentence (amounts, periods, basis, reasons) is written by code from the tool result; the model writes no sentence.
- Before anything is shown, every number in the text and in the Markdown report is checked:
  - amounts, rates, and receipt numbers must be in the tool results;
  - years must be in the tool results or the question; in a clarifying question and in the "이렇게 이해했습니다" line they may also come from the periods the readings propose, since those sentences are shown as readings.
  - An answer with an ungrounded number is withheld.
- The number check only confirms that the same value appears in the evidence. It does not prove that a figure is attached to the right period or that an explanation is right; renderer tests and human review cover that.

## How we got here (measured, including what failed)

All on 13 development questions plus 13 paraphrases written before the comparison runs. "Final" is after a first-pass human review of the visible text against criteria fixed before each run. Full report: [eval/feasibility_2026-10-07/REPORT.md](eval/feasibility_2026-10-07/REPORT.md).

| Design | Result | What it showed |
|---|---|---|
| Model writes the whole answer from correct tool results | automatic 11/13, **final 1/13** | Structured fields were right (numbers 10/10), but the visible text was often one word or omitted the basis or reason |
| Agent: model calls tools and decides, code writes the facts | 23/26 | Better, but decision-stage failures and an explanation asserting an unsupported cause |
| Keyword rules only (baseline) | 25/26 | **Beat the agent**, but its one failure was a confident wrong comparison |
| **Cross-checked reading (current)** | **25/26, 0 confident wrong answers** | The baseline's misreading became a clarifying question; 26 model requests for 26 questions |

The agent did not beat the keyword baseline; the design was changed accordingly. Sampling the model three times at temperature 0.7 found no misreading that the cross-check misses, at three times the cost, so it was not adopted.

**Fixes after an independent review (2026-10-08):** a Codex review found three problems:
- a path that answered from the rules alone when the model failed;
- rules that read unsupported accounts as similar supported ones;
- report and clarifying output that skipped the number check.

After the fixes, the same 26 questions gave the same answers and model readings (25/26, 0 confident wrong answers). On 13 unscored probe questions ([report](eval/3-0b_2026-10-08/REPORT.md)):
- both readers refused five unsupported accounts;
- the model's reading correctly answered two questions the rules could not read ("last year's revenue", the synonym "순익");
- the model misread one question: it read last year's operating income as a point-in-time value. No wrong figure was shown, but a question that could have been answered was refused.

**Limitations of these numbers:**
- One author wrote the questions, paraphrases, probe questions, rules, and prompts.
- The scope is narrow: 3 companies, 6 accounts, 2023–2025.
- The model results come from a single run at temperature 0.
- The human review is a first pass by Claude, not yet confirmed by the user.
- The fair test is the sealed evaluation on four other companies (roadmap 3-1).

## Quick start

```bash
python -m dart_review demo
python -m unittest discover -s tests
python -m dart_review ask "삼성전자 2025년 매출액이 전년보다 얼마나 늘었어?" --no-model --cache demo/opendart --offline
```

With your own OpenDART key in `~/.config/opendart/api_key` (mode 600) and a local Ollama with `gpt-oss:20b`:

```bash
python scripts/fetch_dev_cache.py
python -m dart_review ask "카카오 2024년 3분기 매출은 전년 같은 분기보다 얼마나 줄었어?"
```

Python 3.10+, standard library only.

## Repository map

| Path | What |
|---|---|
| `dart_review/` | client and cache, period/account/comparability rules, tools, renderer, number check, cross-check, CLI, and the account-name vocabulary used to refuse unsupported accounts (`account_vocabulary.json`, names from the development cache only) |
| `eval/` | development questions and gold answers, scorer, runners, run records |
| `demo/` | trimmed OpenDART responses and recorded model readings for the replay demo |
| `docs/` | scope, roadmap, data notes, gold rules, evaluation design, independent reviews (Korean) |

## Safety and reproducibility

- The OpenDART key is read only from `~/.config/opendart/api_key` and never logged, cached, or committed. A public-safety scan (`scripts/check_public_safety.py`: key values, personal data, local paths) is part of the commit routine; it is not enforced by a git hook.
- Raw API responses stay out of the repository (`cache/` is git-ignored) until their redistribution terms are checked; the demo carries only the rows of the six target accounts.
- Four evaluation companies are sealed: development code refuses them. While choosing them, their account row counts and names were seen; no amounts were.
- Evaluation contracts were committed before each run; three independent reviews by another agent (Codex) were reproduced and applied ([docs/reviews/](docs/reviews/)).
- Every evaluation run (`eval/`) records the exact request, the raw response, model digest, the hashes of prompts, tools, and gold, and (since the 3-0b runs) the reference date. The `ask` command does not keep a request log yet.

## License

MIT
