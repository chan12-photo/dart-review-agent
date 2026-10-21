# D5 평가 공식 절차: ⑦ 등록, ⑧ 실행, ⑨ 판정 (계약 6판)

- 작성: 2026-10-21, Claude. [D5 계약](EVAL_CONTRACT_D5.ko.md) 6판의 2·8절과 [D4 절차서](D4_RUN_PROCEDURE.ko.md)를 D5의 파일과 명령으로 옮긴 것이다.
- ⑦에서 등록하는 파일이다. 등록 전 Codex 검토를 받는다. 등록 뒤에는 이 명령만 쓴다.
- 사용자 승인이 필요한 단계에는 **[승인]** 을 적었다. 승인 없이 하지 않는다.
- D4 절차서에서 바뀐 것만 아래에 적고, 판정 파일의 형식, 실패 처리, 다시 돌린 방식의 집계 같은 나머지는 D4 절차서의 ⑧ 6번과 ⑨ 2~4번을 그대로 따른다. 그 경로만 `D4`를 `D5`로 읽는다.
  - 판정 기준은 계약 6절이 D4 4.5에 더한 것을 따른다(재무제표·계정명·기간·금액이 모두 인쇄와 같아야 `ok`).
- **폴더:**

  | 무엇 | 경로 |
  |---|---|
  | 저장소 | `~/Documents/ChatGPT/dart-review-agent` |
  | 평가 문서 PDF (커밋하지 않음) | `~/Desktop/D5/`, `~/Desktop/D5/scans/` |
  | 등록 커밋 R의 작업 폴더 (저장소 밖) | `~/D5_official/checkout` |
  | 사전 점검 로그 (저장소 밖, 실행 폴더의 형제) | `~/D5_official/run1.preflight.json` |
  | 실행 폴더 (실행기가 만든다) | `~/D5_official/run1` |
  | 사람 판정 파일 (실행 폴더마다 따로) | `~/D5_official/judgments/run1/` |

- **파이썬:** 저장소의 가상환경을 쓴다. 명령 블록은 모두 첫 줄에서 `PY`를 정한다. 사전 점검은 작업 폴더에서 **모듈로**(`-m`) 실행한다(D4 절차서 ⑧ 3번의 이유).

## ⑦ 등록

1. 사용자가 매핑표 10개를 확인한다([확인 안내](../eval/d5_eval/REVIEW_GUIDE.ko.md)). Claude가 `status`를 `confirmed`로 바꾸고 `confirmed_by`·`confirmed_at`을 적는다.
   - 결정을 바꿨으면 위치 검사의 자리를 다시 만든다. 먼저 옛 파일을 지우고 `eval/d5_eval/build_places.py --out`을 돌린다.
2. **관문: 확정된 매핑표로 자리를 다시 만들어 등록할 파일과 같은지 본다.**

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   cd ~/Documents/ChatGPT/dart-review-agent && $PY eval/d5_eval/build_places.py --pdf-dir ~/Desktop/D5 --check eval/d5_eval/duplicate_places.json
   ```

   - `the same: 49 places (2 by the wrapped-label fallback)`여야 한다(매핑을 바꾸지 않은 경우).
   - `position_check.py verify`는 쓰지 않는다. 고정 도구는 감긴 계정명 두 곳을 다시 만들지 못한다(계약 6판 11절 1번).
3. 문서 목록과 실행기 입력을 확인한다(아무것도 실행하지 않는다).

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   cd ~/Documents/ChatGPT/dart-review-agent && $PY eval/d4_eval/run_d4.py --documents eval/d5_eval/documents.json --pdf-dir ~/Desktop/D5 --scan-dir ~/Desktop/D5/scans --out ~/D5_official/never --dry-run
   ```

   마지막 줄이 `80 calls; inputs match the registered documents; nothing was run`이어야 한다.
4. 매핑표와 (바뀌었다면) 자리 파일을 커밋한다(커밋 관문).
5. 깨끗한 트리에서 등록 기록을 만든다.
   - `register --profile d5`는 다음을 확인하고, 하나라도 아니면 거부한다.
     - 트리가 깨끗하다.
     - 파일이 모두 커밋돼 있고, 링크가 아니다.
     - 매핑표가 확정됐다.
     - 목록·자리·정답·매핑표·대응표가 모두 들어 있다.
     - 목록이 N = 10이다.
     - 로컬과 `origin`의 `d5-frozen`이 F이고, HEAD가 F의 자손이며, 고정 기록이 F의 것이다.

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   cd ~/Documents/ChatGPT/dart-review-agent && $PY eval/d4_preflight.py register --profile d5 --freeze eval/freeze_d5.json --paths $(git -c core.quotepath=off ls-files eval/d5_excluded.json eval/d5_candidates eval/d5_eval eval/d4_population.json eval/d4_population.py eval/d4_download.py eval/d4_eval/run_d4.py eval/d4_eval/position_check.py eval/d4_eval/official_d4.py eval/d4_eval/document_list.py docs/EVAL_CONTRACT_D5.ko.md docs/D5_RUN_PROCEDURE.ko.md) --out eval/register_d5.json --remote origin
   ```

6. `eval/register_d5.json` **하나만** 커밋한다. 이것이 R이다. R의 부모는 등록 시점의 HEAD 하나여야 한다(병합 커밋은 안 된다). 태그를 단다: `git tag -a d5-registered -m "D5 registration R"`.
7. **[승인]** R까지의 커밋과 태그를 push한다: `git push origin main`, `git push origin d5-registered`. 태그는 옮기지 않는다.

## ⑧ 실행

1. R을 저장소 밖의 새 작업 폴더로 꺼낸다: `cd ~/Documents/ChatGPT/dart-review-agent && git worktree add ~/D5_official/checkout d5-registered`
2. 모델 서버를 다른 터미널에서 띄운다(이 명령만): `OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve`
3. 사전 점검:

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   cd ~/D5_official/checkout && $PY -m eval.d4_preflight check --profile d5 --freeze eval/freeze_d5.json --register eval/register_d5.json --registered d5-registered --remote origin --log ~/D5_official/run1.preflight.json
   ```

   - 모든 줄이 `ok`여야 한다. 하나라도 `FAIL`이면 실행하지 않는다. 실패한 로그도 보관한다.
   - D5에서 더 확인하는 것:
     - 고정 기록의 프로필
     - 등록 기록의 프로필·태그·F
     - F와 `based_on`, R의 관계(R은 등록 기록만 더한 단일 부모 커밋)
     - 고정·등록 기록이 일반 파일인지
4. 입력 확인: ⑦ 3번의 명령을 작업 폴더에서 `--out ~/D5_official/run1 --dry-run`으로 다시 돌린다.
5. **[승인]** 실행. 전원을 연결하고 저장 공간을 확인한 뒤, 앱과 분리해(`nohup`) 잠자기를 막고(`caffeinate -i`) 돌린다. D4는 규칙 약 9분, AI 약 112분이 걸렸다.

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   cd ~/D5_official/checkout && nohup caffeinate -i $PY eval/d4_eval/run_d4.py --documents eval/d5_eval/documents.json --pdf-dir ~/Desktop/D5 --scan-dir ~/Desktop/D5/scans --out ~/D5_official/run1 --preflight ~/D5_official/run1.preflight.json > ~/D5_official/run1.console.txt 2>&1 &
   ```

   - 실행기는 점검 로그의 프로필이 `d5`인지도 확인한다.
   - 실행 중에는 저장소의 제품·도구 파일을 바꾸지 않는다(계약 8절).
6. 종료값과 실패: D4 절차서 ⑧ 6번과 같다.
7. 모델 서버를 끈다. 작업 폴더는 ⑨가 끝날 때까지 지우지 않는다.

## ⑨ 판정과 공식 결과

1. 판정할 것 목록:

   ```bash
   PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
   mkdir -p ~/D5_official/judgments/run1 && cd ~/D5_official/checkout && $PY eval/d4_eval/official_d4.py --documents eval/d5_eval/documents.json --places eval/d5_eval/duplicate_places.json --run ~/D5_official/run1 --judgments ~/D5_official/judgments/run1 --out ~/D5_official/official.draft1.json
   ```

   - 공식 집계는 프로필의 자리 파일만 받고, N(10)을 고정 기록에서 읽는다. 묶음마다 호출이 정확히 10개(텍스트)·30개(스캔)일 때만 판정한다.
2. 판정 파일: D4 절차서 ⑨ 2번과 같다. 판정 근거에는 계약 6절대로 PDF 쪽, 인쇄 행, 기간 머리글, 인쇄 금액을 적는다.
3. 다시 집계(새 파일 이름), 방식을 다시 돌린 경우: D4 절차서 ⑨ 3·4번과 같다. 명령에 `--documents eval/d5_eval/documents.json --places eval/d5_eval/duplicate_places.json`을 붙인다.
4. 보관: 저장소의 `eval/d5_eval/results/<날짜>/`에 다음을 넣고 커밋한다. push는 **[승인]**.
   - 실행 폴더
   - 점검 로그
   - 판정 파일
   - 집계 결과
5. 보고(계약 7·10절, D4 계약 5·9절):
   - 공식 판정
   - S1을 채점기의 몫과 위치 검사의 몫으로 나눠서
   - 칸·문서·매핑 결정·사람 판정 수
   - "제목 미확인 표"의 수와 칸 수
   - 실패한 호출과 원인
   - 한계
6. 결과 Codex 검토 뒤 공개한다(계약 1절).
