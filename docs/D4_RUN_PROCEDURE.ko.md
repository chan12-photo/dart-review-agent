# D4 공식 절차: ⑦ 등록, ⑧ 실행, ⑨ 판정 (계약 7판)

- 작성: 2026-10-19, Claude. 계약 [`EVAL_CONTRACT_D4.ko.md`](EVAL_CONTRACT_D4.ko.md) 7판의 1.2, 4.5, 4.6, 5, 7절을 명령으로 옮긴 것이다. ⑦에서 등록하는 파일이다. 등록 뒤에는 이 명령만 쓴다(1.3).
- 사용자 승인이 필요한 단계에는 **[승인]** 을 적었다. 승인 없이 하지 않는다.
- 폴더 (모두 저장소 밖):

  | 무엇 | 경로 |
  |---|---|
  | 평가 문서 PDF (커밋하지 않음, 계약 8) | `~/Desktop/D4/`, `~/Desktop/D4/scans/` |
  | 등록 커밋 R의 작업 폴더 | `~/D4_official/checkout` |
  | 사전 점검 로그 | `~/D4_official/run1.preflight.json` (실행 폴더의 **형제**, Codex 7차 3번) |
  | 실행 폴더 | `~/D4_official/run1` (실행기가 만든다. 미리 만들지 않는다) |
  | 사람 판정 파일 | `~/D4_official/judgments/` |

- 파이썬: 저장소의 가상환경 `~/Documents/ChatGPT/dart-review-agent/.venv/bin/python`(아래 `$PY`). 제품(`dart_review`)은 이 가상환경에 설치돼 있지 않다. 그래서 작업 폴더 안에서 실행해 **그 폴더의 제품**을 불러온다.

## ⑦ 등록

1. 사용자가 매핑표 10개를 확인한다. Claude가 `status`를 `confirmed`로 바꾸고 `confirmed_by`·`confirmed_at`을 적어 커밋한다(커밋 관문을 지난다).
2. 깨끗한 트리에서 등록 기록을 만든다(`register`는 트리가 깨끗하지 않거나, 커밋되지 않은 파일이나 확정되지 않은 매핑표가 있으면 거부한다).

   ```bash
   .venv/bin/python eval/d4_preflight.py register --freeze eval/freeze_d4.json --paths $(git -c core.quotepath=off ls-files eval/d4_population.json eval/d4_excluded.json eval/d4_population.py eval/d4_download.py eval/d4_candidates eval/d4_eval docs/EVAL_CONTRACT_D4.ko.md docs/D4_RUN_PROCEDURE.ko.md) --out eval/register_d4.json
   ```

   등록되는 것:
   - 고정 기록, 모집단, 제외 목록, 후보 판정·받기 기록(30개와 `downloads.jsonl`·`checks.jsonl`)
   - 문서 목록 `eval/d4_eval/documents.json`
   - 정답 10개와 확정 매핑표 10개, 스캔 대응표 30개
   - 위치 검사의 등록 자리 `eval/d4_eval/duplicate_places.json`(60곳)
   - 실행기 `run_d4.py`, 위치 검사 `position_check.py`, 공식 집계 `official_d4.py`, 계약, 이 절차서
3. `eval/register_d4.json`을 커밋한다. 이것이 R이다. 태그를 단다: `git tag -a d4-registered -m "D4 registration R"`.
4. **[승인]** R까지의 커밋과 태그를 GitHub에 push한다: `git push origin main`, `git push origin d4-registered`. push 시각이 공개 기록이다. 태그는 옮기지 않는다.

## ⑧ 실행

1. R을 저장소 밖의 새 작업 폴더로 꺼낸다(저장소 폴더에서): `git worktree add ~/D4_official/checkout d4-registered`
2. 모델 서버를 다른 터미널에서 띄운다(계약 7, 이 명령만): `OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve`
3. 사전 점검. 작업 폴더에서 **모듈로** 실행한다.

   ```bash
   cd ~/D4_official/checkout && $PY -m eval.d4_preflight check --freeze eval/freeze_d4.json --register eval/register_d4.json --registered d4-registered --remote origin --log ~/D4_official/run1.preflight.json
   ```

   - 모든 줄이 `ok`여야 한다. 하나라도 `FAIL`이면 실행하지 않는다. 실패한 로그도 보관한다.
   - **모듈로 실행하는 이유:** 고정 도구의 사용 예시(`python eval/d4_preflight.py check`)대로 하면 스크립트 폴더(`eval/`)만 경로에 들어가서, 제품을 불러오는 줄에서 `ModuleNotFoundError: No module named 'dart_review'`로 멈춘다(2026-10-19 확인. 틀린 결과가 아니라 실행이 멈춘다). `-m`으로 작업 폴더에서 실행하면 그 폴더의 제품을 불러오고 "dart_review imported from this checkout"를 통과한다. 고정 도구(T)는 바꾸지 않는다.
   - 로그는 실행 폴더 **밖, 옆**에 쓴다. 실행 폴더 안에 쓰면 폴더가 생겨 실행기가 거부하고, 작업 폴더 안에 쓰면 트리가 더러워진다.
4. 입력 확인(아무것도 실행하지 않는다):

   ```bash
   $PY eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out ~/D4_official/run1 --dry-run
   ```

   마지막 줄이 `80 calls; inputs match the registered documents; nothing was run`이어야 한다.
5. **[승인]** 실행. 하루 이상 걸릴 수 있어 잠자기를 막는다(`caffeinate -i`).

   ```bash
   caffeinate -i $PY eval/d4_eval/run_d4.py --pdf-dir ~/Desktop/D4 --scan-dir ~/Desktop/D4/scans --out ~/D4_official/run1 --preflight ~/D4_official/run1.preflight.json
   ```

   실행기는 시작 전에 다음을 확인하고, 하나라도 아니면 아무것도 실행하지 않는다(종료값 2).
   - 실행 폴더가 없고 작업 폴더 밖이다.
   - 점검 로그가 작업 폴더 밖이고, 모든 항목이 통과했고, 지금 HEAD를 점검했다.
   - 작업 폴더가 여전히 깨끗하다.
6. 종료값:
   - **0:** 80회 모두 종료값 0. 채점의 `official_ready`와는 다르다. 그것은 ⑨에서 정한다.
   - **1:** 실패한 호출이 있다. `run.json`의 `failed`와 `run_log.jsonl`의 `stderr_tail`을 본다. 모델 서버 장애(연결 실패 등)이면 계약 7에 따라 그 방식 전체를 새 폴더에서 다시 돌린다. 새 점검 로그를 만들고(`run2.preflight.json`) `--readers ai --out ~/D4_official/run2`로 실행한다. 두 폴더를 모두 보관한다. 출력 한도 초과는 장애가 아니다.
7. 모델 서버를 끈다(띄운 터미널에서 Ctrl-C). 작업 폴더는 ⑨가 끝날 때까지 지우지 않는다.

## ⑨ 판정과 공식 결과

1. 판정할 것 목록(실행 폴더에 아무것도 쓰지 않는다):

   ```bash
   cd ~/D4_official/checkout && $PY eval/d4_eval/official_d4.py --run ~/D4_official/run1 --judgments ~/D4_official/judgments --out ~/D4_official/official.draft1.json
   ```

   호출마다 다음 두 가지가 나온다.
   - `extras_to_judge`: 정답에 없는 표시 없는 칸(4.5)
   - `position_places`: 상태가 `needs_verdict`인 곳(4.6)
2. Claude가 1차로 판정하고 근거를 적는다. 사용자가 확인한다(계약 6). 판정 파일은 호출마다 둘이다. 둘 다 그 보고서의 SHA-256(`report_sha256`, 집계 출력에 있다)과 `judged_by`를 적는다.
   - `~/D4_official/judgments/<이름>.extras.json`: `{"report_sha256", "judged_by", "verdicts": {"<칸 id>": {"verdict": "wrong"|"ok", "note"}}}`
   - `~/D4_official/judgments/<이름>.position.json`: `{"report_sha256", "judged_by", "verdicts": {"<자리 id>": {"verdict": "wrong"|"ok", "wrong_unmarked": n, "note"}}}`
     - `n`은 채점기가 "맞음"으로 센 칸(집계 출력의 각 행 `scorer`가 `correct`) 가운데, 다른 인쇄 행의 자리에 있고 표시가 없는 칸의 수다.
     - 채점기가 틀림으로 센 칸은 이미 S1에 있다. 정답 밖의 칸(`not_in_gold`)은 extras 판정에서 다룬다. 둘 다 여기서 세지 않는다(두 번 세지 않기, 계약 4.6).
   - `<이름>`은 `<문서 key>.<text|normal|tilt|blur>.<rules|ai>`.
3. 다시 집계한다(새 파일 이름. `--out`은 덮어쓰지 않는다). 묶음(3.1, 3.3)과 방식마다 판정이 나온다.
   - `met` / `not met`: 묶음의 모든 호출이 `official_ready`일 때만 나온다.
   - `not official`: 아직 판정이 남았거나 보고서가 없는 호출이 있다(이유가 함께 나온다).

   **제품 판정은 AI 방식이다.**
4. 보관: 저장소(등록 작업 폴더가 아닌 원래 폴더)의 `eval/d4_eval/results/<날짜>/`에 다음을 넣고 커밋한다(커밋 관문). push는 **[승인]**.
   - 실행 폴더
   - 점검 로그
   - 판정 파일
   - 집계 결과(초안 포함)
5. 보고(계약 5, 9):
   - 공식 판정
   - 고정 채점기만의 S1과 위치 검사의 S1(`S1_position`)을 나눠서
   - 칸 수, 문서 수, 매핑표 결정 수, 사람 판정 수
   - 실패한 호출
   - 위 모든 한계
