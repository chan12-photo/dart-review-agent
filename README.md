# dart-review-agent

**Status: work in progress (draft README, 2026-10-08).** Results below are from self-authored development questions; the sealed, pre-registered evaluation has not been run yet. Korean version: [README.ko.md](README.ko.md).

A local tool that answers questions like *"How much did Samsung Electronics' revenue grow in 2025?"* from OpenDART financial statements. It compares figures across periods only when the comparison is sound (same consolidated/separate basis, same period length, same currency, no unexplained restatement), refuses or asks back otherwise, and never shows a number that is not in a verified tool result.

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

The rules for all of these are code, tested on the real cache, and each trap test was shown to fail when its rule is replaced by a naive version (10 of 10 caught).

## How it works (cross-checked reading)

```text
question ──► keyword rules ──► reading A ─┐
         └─► local model   ──► reading B ─┤ same?  ── yes ─► tool (rules on OpenDART data) ─► code writes the answer ─► number check ─► answer
                                          └─ no ──► show both readings and ask which one was meant
```

- Two independent readers interpret the question: keyword rules and a local model (`gpt-oss:20b` via Ollama, one structured request). Code answers only when they agree.
- Every factual sentence (amounts, periods, basis, reasons) is written by code from the tool result. Before anything is shown, every number in the text is checked against the tool results; an answer with an ungrounded number is withheld.
- The model never writes numbers that reach the user.

## How we got here (measured, including what failed)

All on 13 development questions plus 13 paraphrases written before the comparison runs. "Final" is after a first-pass human review of the visible text against criteria fixed before each run. Full report: [eval/feasibility_2026-10-07/REPORT.md](eval/feasibility_2026-10-07/REPORT.md).

| Design | Result | What it showed |
|---|---|---|
| Model writes the whole answer from correct tool results | automatic 11/13, **final 1/13** | Structured fields were right (numbers 10/10), but the visible text was often one word or omitted the basis or reason |
| Agent: model calls tools and decides, code writes the facts | 23/26 | Better, but decision-stage failures and an explanation asserting an unsupported cause |
| Keyword rules only (baseline) | 25/26 | **Beat the agent**, but its one failure was a confident wrong comparison |
| **Cross-checked reading (current)** | **25/26, 0 confident wrong answers** | The baseline's misreading became a clarifying question; 26 model requests for 26 questions |

The agent did not beat the keyword baseline; the design was changed accordingly. Sampling the model three times at temperature 0.7 found no misreading that the cross-check misses, at three times the cost, so it was not adopted.

**Limitations of these numbers:** one author wrote the questions, paraphrases, rules, and prompts; the scope is narrow (3 companies, 6 accounts, 2023–2025); the human review is a first pass by Claude, not yet confirmed by the user. The fair test is the sealed evaluation on four other companies (roadmap 3-1).

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
| `dart_review/` | client and cache, period/account/comparability rules, tools, renderer, number check, cross-check, CLI |
| `eval/` | development questions and gold answers, scorer, runners, run records |
| `demo/` | trimmed OpenDART responses and recorded model readings for the replay demo |
| `docs/` | scope, roadmap, data notes, gold rules, evaluation design, independent reviews (Korean) |

## Safety and reproducibility

- The OpenDART key is read only from `~/.config/opendart/api_key` and never logged, cached, or committed. A public-safety scan (`scripts/check_public_safety.py`: key values, personal data, local paths) is part of the commit routine; it is not enforced by a git hook.
- Raw API responses stay out of the repository (`cache/` is git-ignored) until their redistribution terms are checked; the demo carries only the rows of the six target accounts.
- Four evaluation companies are sealed: development code refuses them.
- Evaluation contracts were committed before each run; two independent reviews by another agent (Codex) were reproduced and applied ([docs/reviews/](docs/reviews/)).
- Every model run records the exact request, the raw response, model digest, and the hashes of prompts, tools, and gold.

## License

MIT
