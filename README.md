# dart-review-agent

A local tool that **looks up and compares** financial figures of Korean listed companies from their filed statements (OpenDART). It compares two periods only when the comparison is sound: within the reports it reads, the same consolidated/separate basis, period length, and currency, and no visible restatement. Otherwise it refuses or asks back, and says why. It does not check amendments it has not fetched. Korean version: [README.ko.md](README.ko.md).

**v0.1 (2026-10-09).** In one line: **a rule-based financial comparison tool, plus an experiment in cross-checking it with an LLM.** Two pre-registered evaluations were run:

| Evaluation | Questions | Official verdict | Product's wrong figures | Solved (product / rules only) | LLM: wrong figures prevented / answers lost |
|---|---|---|---|---|---|
| 3-1 sealed | 36 written by people | **criteria not met** (a scorer mismatch in a comparison method) | 0 of 22 figure answers | 22/23 / **23/23** | 0 / 1 |
| 3-5 large template | 600 generated from templates | **criteria met** (with the scorer fixed after 3-1 and the run-commit condition relaxed after the runs, P5) | 0 of 419 figure answers | 419/480 / **476/480** | 0 / **62** (57 answerable, 5 traps) |

- In both, the product gave **no wrong figure**.
- **The keyword rules alone solved more.** The LLM cross-check prevented no wrong figure and, through misreadings and output-limit stops, lost questions that were otherwise handled correctly.
- Both use four companies, and the 3-5 questions are template-generated; neither is a general accuracy figure.

`dart_review/` in v0.1.0 is identical to the frozen commit P (`c182075`) that was evaluated. v0.1.1 changes wording only: tool notes and reasons are shown in the polite style, and the account clarifying question no longer assumes a comparison. No status or figure changed; the replay test checks this against the saved runs.

**v0.1.2** fixes the product defects 3-5 found:
- an official English company name in the model's reading is mapped to the registered Korean name (corpCode.xml);
- an unknown company written in the question is refused as out of scope;
- two refusals agree;
- a row that is not found gives a figure-free "확인 필요" instead of "no data";
- one non-standard account name is added, and two wordings are fixed.

Replaying the recorded 3-5 model replies, 22 questions improve and none gets worse. Those questions have been seen, so this is not an evaluation result; v0.1.2 is to be measured on new questions.

```text
$ python -m dart_review demo        # no API key, no model server, no network
## 삼성전자 매출액
**검증 상태:** 비교 가능
| 구분 | 기준 | 기간 | 금액(원) | 보고서 | 접수번호 |
| 비교 기간 | 연결 | 2025년 연간(1~12월) | 333,605,938,000,000 | 2025년 사업보고서 | 20260310002820 |
| 기준 기간 | 연결 | 2024년 연간(1~12월) | 300,870,903,000,000 | 2025년 사업보고서 | 20260310002820 |
**변화:** 32,735,035,000,000원 (10.88%, 증가)
```

## Sealed evaluation (3-1, pre-registered)

- Four companies never used in development (NAVER, CJ CheilJedang, E-MART, LG Energy Solution) and 36 questions:
  - 14 written by the user without seeing the data;
  - 22 written by Claude.
- Questions, gold answers, criteria, and the frozen product commit were committed before any run (pre-registration R = `c9a4a55`). Each of three methods then ran once.

| Method | 23 figure questions correct | 13 refuse/clarify correct | **Wrong figures** | Other failures | Model time |
|---|---:|---:|---:|---|---:|
| Keyword rules only | **23** | 13 | **0** | none | 0 |
| **Cross-checked (product)** | 22 | 13 | **0** | 1 unnecessary clarification | 8.7 min |
| Model reading only | 21 | 10 | **0** | 4 wrong refusals, 1 wrong clarification (2 of these from a scorer mismatch) | 12.1 min |

- **The official verdict is "criteria not met".**
  - All four criteria on the product were met: 0 wrong figures, 22/23 solved (criterion ≥ 70%), 4.3% unnecessary-clarification cost (criterion ≤ 25%), 10/10 on out-of-scope and ambiguous questions.
  - The miss came from the "model reading only" comparison method. It prefixes answers with "이렇게 이해했습니다: …2025년…" ("Here is how I read it"), and the frozen scorer counted that year as an ungrounded number.
  - This is a mismatch between the product design (reading years are allowed) and the scorer. Two independent reviews before the run did not catch it. The scorer was not changed after the run; the result with the year allowed is reported only as a sensitivity check.
- **On these 36 questions the LLM added nothing.** Rules wrong and model right: 0. Wrong figures the cross-check prevented: 0. Instead, a model misreading (revenue read as a point-in-time value) turned one answerable question into a clarifying question.
- **What happened when the model read alone:**
  - it refused answerable questions after misreading the period or the account;
  - it gave a wrong reason for a refusal ("unsupported company" when the question named several companies);
  - at temperature 0, byte-identical requests got different readings in different runs.
- **How much "0" means:**
  - It is an observation on these 36 questions. With 0 errors in 22 answered figure questions, the 95% upper bound is about 13%.
  - Most questions were plain 2024–2026 lookups and comparisons. Few hard cases appeared: restatements, sign changes, mislabeled account ids.
  - So the rules getting everything right says more about the questions staying inside the rules' range than about the rules being strong.

Full report (Korean): [eval/sealed_3-1/REPORT.md](eval/sealed_3-1/REPORT.md). Contract: [docs/EVAL_CONTRACT_3-1.ko.md](docs/EVAL_CONTRACT_3-1.ko.md).

## Large template evaluation (3-5, pre-registered)

- **Method:** 600 questions about the same four companies, generated from fixed templates. This evaluation was committed to before 3-1's results were known.
  - Generation: every company x basis x account x period combination was listed, and the questions were drawn with a fixed seed.
  - Composition: 480 answerable questions (lookups, prior-year comparisons, balance-sheet comparisons across two reports, consolidated vs separate) and 120 traps (fourth-quarter three months, quarterly cash flow, 2014, out of scope, ambiguous, compound).
  - Pre-registration: the questions, gold answers, criteria, and product v0.1.1 were committed before the runs, after a Codex review.

| Criterion | Cross-check (product) | Met |
|---|---|---|
| Wrong figure answers 0 | **0** (419 figure answers) | yes |
| Solved ≥ 80% | 419/480 = 87.3% | yes |
| Traps ≥ 90% | 112/120 = 93.3% | yes |
| Ungrounded numbers 0 | 0 | yes |

- **The verdict depends on a scorer fix.** With the 3-1 scorer, the reading years shown in 8 clarifying questions would count as ungrounded numbers, and the criteria would not be met. The fix corrects the mismatch found in 3-1; it was written into the contract, reviewed, and pre-registered before the 3-5 runs.
- **A verdict condition was also relaxed after the runs (P5).** The contract commits each run before the next, but the judge required both runs to come from one commit. It now treats commits that differ only by run records as the same code. Without P5 the verdict would have been "suspended". Scores and thresholds are unchanged.
- **Rules only:** 476/480 (99.2%), no wrong figure. The four failures are Emart's non-standard cash-flow rows.
- **LLM:** 0 wrong figures prevented, 62 answers lost (57 answerable questions, 5 correctly handled traps).
  - The two readings differed in 40 questions: quarter ends read as three months (16), the company written in English (14), annual flows read as year-end values (4), a different year (3), a group name taken as one company (2), the ambiguous "이익" taken as one account (1). 37 of them became unnecessary clarifications.
  - 24 withheld answers after the model hit its output limit.
- **Reference error-rate figure:** 0 wrong among 419 figure answers gives about 0.71%. This assumes independent trials, so it is not a strict upper bound. The 419 answers referenced raw evidence rows 730 times, 642 distinct rows.
- **Product defects found (not fixed during the evaluation):** company names in the model's reading are not normalized; a non-standard account name is unknown, and the answer then wrongly says there is no data; unknown companies are not refused as out of scope.

Full report (Korean): [eval/template_3-5/REPORT.md](eval/template_3-5/REPORT.md). Contract: [docs/EVAL_CONTRACT_3-5.ko.md](docs/EVAL_CONTRACT_3-5.ko.md).

## What it does

| Feature | Example question | Answer |
|---|---|---|
| Value lookup | "삼성전자 매출 알려줘" (Samsung's revenue) | value, period, basis (consolidated/separate), report and receipt number; if the same report type a year later exists, it is checked for restatement, otherwise the answer says restatement was not checked |
| Period comparison | "카카오 2024년 3분기 매출은 전년 같은 분기보다 얼마나 줄었어?" | both values, change, rate, direction (e.g. turned to profit when the sign changes) |
| Consolidated vs separate | "삼성전자 연결 매출이랑 별도 매출 보여줘" | both values and the gap, explained only as a difference in scope, never a guessed cause |
| Asking back | "삼성전자 이익이 얼마나 늘었어?", "삼성 매출 알려줘" | asks whether operating income or net income is meant, or which company |
| Refusal with a reason | "삼성전자 유동자산 알려줘", "카카오뱅크 매출 알려줘", "삼성전자 2014년 매출 비교해 줘" | names the unsupported account or company; a period OpenDART does not provide is reported as no data, not as an error |

- **Companies:** 3 for development (Samsung Electronics, Kakao, Celltrion). The evaluation runner (`eval/run_eval.py --companies sealed-3-1`) uses the four sealed ones. Financial companies are excluded because their statements are structured differently.
- **Accounts:** 6 (revenue, operating income, net income, operating cash flow, total assets, total liabilities).
- **Periods:** annual, three-month quarters, year to date, point in time.
- **Data checked:** development companies 2023–2025, evaluation companies 2022–2026.
- **Company aliases:** read from a fixed table ("삼전" in development; "네이버", "엔솔" and others for evaluation). A different company whose name contains a supported one (e.g. 카카오뱅크) is never read as that company.

## Why this is harder than it looks

The same OpenDART column means different things depending on the report and the statement. These were checked against 72 cached development reports ([data notes](docs/DATA_NOTES.ko.md)):

- In quarterly income statements `thstrm` is the three months; in quarterly cash flow statements it is already year to date.
- In quarterly balance sheets the "prior period" column is the **prior year end**, not the same quarter of the prior year.
- Later reports **restate** earlier figures (Kakao, Celltrion, and CJ CheilJedang's liabilities in the sealed evaluation).
  - Kakao's Q3 2024 revenue change is −4.48% against the restated prior figure.
  - Against the originally filed figure it is −11.08%.
- Account ids can be wrong: Kakao's 2023 quarterly revenue is tagged `ifrs-full_GrossProfit`.

The rules for all of these are code, tested on the real cache. Each trap test was shown to fail when its rule is replaced by a naive version (11 of 11 caught, `scripts/check_trap_tests.py`).

## How it works (cross-checked reading)

```text
question ──► keyword rules ──► reading A ─┐
         └─► local model   ──► reading B ─┤ same?  ── yes ─► tool (rules on OpenDART data) ─► code writes the answer ─► number check ─► answer
                                          └─ no ──► show both readings and ask which one was meant
```

- **Two readers interpret the question separately.**
  - One is the keyword rules.
  - The other is a local model (`gpt-oss:20b` via Ollama), asked once for a structured reading, with a reference date in the prompt.
  - If they agree, code answers; if not, it asks back.
  - Both were built by one author from one table of defaults, so their errors are not guaranteed to be independent.
- **When only one reader produces a reading:**
  - if the model's reading is missing, nothing is answered;
  - if the rules cannot read the question and the model can (e.g. the synonym "순익"), the answer starts with the model's reading in code-written words ("이렇게 이해했습니다: …"), so a misreading is visible;
  - `--no-model` is an explicit rules-only mode chosen by the user, and the answer says so.
- **An unsupported account is refused, never read as a similar supported one.** This includes names that contain a supported one, such as 유동자산 (current assets, not total assets) or 매출원가 (cost of sales, not revenue).
- **Code writes every sentence.** Every factual sentence (amounts, periods, basis, reasons) is written by code from the tool result; the model writes none.
- **Numbers are checked before anything is shown**, in the text and in the Markdown report:
  - amounts, rates, and receipt numbers must be in the tool results;
  - years must be in the tool results or the question; in a clarifying question and in the "이렇게 이해했습니다" line they may also come from the periods the readings propose;
  - an answer with an ungrounded number is withheld;
  - the check only confirms that the same value appears in the evidence. Whether it is attached to the right period is covered by renderer tests and human review.

## How we got here (including what failed)

The design was chosen on 13 development questions plus 13 paraphrases ([report](eval/feasibility_2026-10-07/REPORT.md)).

| Design | Result | What it showed |
|---|---|---|
| Model writes the whole answer from correct tool results | automatic 11/13, **1/13 after reviewing the text** | Structured fields were right, but the text was often one word or omitted the basis or reason |
| Agent: model calls tools and decides | 23/26 | Decision-stage failures; an explanation asserting an unsupported cause |
| Keyword rules only | 25/26 | **Beat the agent**, but its one failure was a confident wrong comparison |
| **Cross-checked reading (current)** | **25/26, 0 confident wrong answers** | The rules' misreading became a clarifying question |

- The agent did not beat the keyword baseline, so the design was changed.
- At this stage the cross-check stopped one misreading by the rules. In the sealed evaluation there was none to stop.

## How it was evaluated

- **Pre-registration:** the contract, the frozen product (P), and the questions were committed before any data was seen. The user's questions were committed first only as a hash.
- **Gold answers:** computed separately from the raw cells, then compared with the product's rules.
  - The one disagreement (C06) was resolved by re-reading the raw data: a restatement was found, the gold answer was corrected, and the user approved.
  - Because the comparison with the product prompted that re-check, the correction is not fully independent. The report says so and gives the sensitivity.
- **Judging:** Claude reviewed the visible text of each method first; the user confirmed. A strict judge (`eval/judge.py`) then ran once. It withholds a verdict if any hash does not match.
- **Independent reviews:** another agent (Codex) reviewed the work five times. Each finding was reproduced and the decision on it recorded ([docs/reviews/](docs/reviews/)). Before the run they caught evaluator defects such as a crash in review-sheet generation and a missing cross-run check of the sealed hashes.

## Limitations

- 7 companies, 6 accounts, one run per method.
- The sealed questions were easy. 22 of 36 were written by someone who knew the product design (Claude).
- Human review is a first pass by Claude confirmed by the user; there is no independent third reviewer.
- The local model is not deterministic even at temperature 0.
- Not covered: financial companies' statements, questions about several companies or accounts at once, explaining *why* a figure changed.
- The 3-5 questions are mechanical. Its human review covered all failures and a sample of 60 passed answers.
- Next is fixing the defects 3-5 found. A fixed version is to be measured on new questions, not on ones whose results have been seen.

## Status and next tasks (2026-10-10)

This repository is closed for now at v0.1.2. Deferred tasks, and when they would be picked up:

| Task | What | Why deferred / when to resume |
|---|---|---|
| 3-6 re-evaluation | Measure v0.1.2 on new companies and free-form questions written by people; the 3-1 and 3-5 questions have been seen and are not reused | The two evaluations complete the current claims; to be done together with a policy change |
| Cross-check policy | Answer with the rules when they read the question; use the LLM only for questions the rules cannot read | In both 3-1 and 3-5 the LLM prevented no wrong figure and only lost answers; decide after comparing on the same questions in 3-6 |
| Review memo | The comparison as a Markdown memo with sources | Covered first in another project (documents to spreadsheets) |
| MCP adapter | The same tools from external clients | When there is a client to connect |
| Reasons for a change (RAG) | Cite sentences from the filings that explain a change | The largest task; needs its own evaluation design |

Details: [docs/ROADMAP.ko.md](docs/ROADMAP.ko.md) (Korean).

## Quick start

Python 3.10+, standard library only.

```bash
python -m dart_review demo
python -m unittest discover -s tests
python -m dart_review ask "삼성전자 매출 알려줘" --no-model --cache demo/opendart --offline --reference-date 2026-10-08
```

Without `--reference-date` the reference date is today. A question with no year uses the latest annual report as of that date, which may be a year the demo data does not have.

With your own OpenDART key in `~/.config/opendart/api_key` (mode 600; `DART_API_KEY_FILE` changes the location) and a local Ollama with `gpt-oss:20b`:

```bash
python scripts/fetch_dev_cache.py
python -m dart_review ask "카카오 2024년 3분기 매출은 전년 같은 분기보다 얼마나 줄었어?"
```

## Repository map

| Path | What |
|---|---|
| `dart_review/` | client and cache, period/account/comparability rules, company-name matching, tools, renderer, number check, cross-check, CLI |
| `eval/` | questions and gold answers, gold builders, scorer, judge, run records; the sealed evaluation is in `eval/sealed_3-1/` |
| `demo/` | trimmed OpenDART responses and recorded model readings for the replay demo |
| `docs/` | scope, roadmap, data notes, gold rules, evaluation design and contract, independent reviews, pre-publication check (Korean) |
| `scripts/` | cache fetching, demo fixtures and vocabularies, trap-test check, public-safety scans |

## Data source and use

- **Data source: Financial Supervisory Service, OpenDART (opendart.fss.or.kr).**
- Raw responses are not in the repository (`cache/` is git-ignored). The repository holds only:
  - the trimmed demo responses (target-account rows only, 73 of 1,012 rows);
  - the account rows and figures that appear in gold answers and run records.
- No clause in the OpenDART terms of use (effective 2020-01-21) directly forbids redistributing disclosed data. That is not a confirmed permission: copyright matters not covered there follow the Copyright Act and the Public Data Act (Article 16 ④). This is a pre-publication check, not legal advice ([pre-publication check](docs/PUBLICATION_CHECK.ko.md)).
- The filing companies and OpenDART are responsible for the original disclosures. The figures here come from responses fetched on 2026-10-07 and 2026-10-08.
- The output of this tool is not investment advice.

## Safety and reproducibility

- The OpenDART key is read from `~/.config/opendart/api_key` by default (`DART_API_KEY_FILE` changes the location). Its value is never logged, cached, or committed.
- Two scans ran before publication with 0 findings within their scope. That does not prove there is no secret: values that do not match a pattern (encoded values, binary files) are not caught.
  - the current files (`scripts/check_public_safety.py`);
  - the whole git history (`scripts/check_history_safety.py`). The match against the local key value runs only on the author's machine, where the key file exists; CI runs the pattern checks only.
  - Both print only the kind and place of a finding, never the matched value.
- Every evaluation run records the exact request, the raw response, the model digest, hashes of prompts, tools, and gold, and the reference date. The `ask` command keeps no request log.

## License

The code is MIT-licensed (`LICENSE`). The figures and demo responses from OpenDART are not newly licensed by it; see "Data source and use" above.
