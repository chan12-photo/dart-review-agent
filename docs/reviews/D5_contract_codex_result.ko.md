# D5 계약·도구 Codex 검토 결과

- 검토일: 2026-10-20
- 대상: `git diff 14b853c..d5-tools`, `docs/EVAL_CONTRACT_D5.ko.md`, `docs/EVAL_PLAN_D5.ko.md`, D4 공식 저장 기록
- 제약 준수: OpenDART 요청·인증키·네트워크·Ollama를 쓰지 않았다. 제품 추출과 `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행은 하지 않았다. D4 PDF에는 정답 생성기와 위치 검사만 썼고, 저장된 제품 보고서만 다시 채점했다.

## 결론

④ 고정 전 보완이 필요하다. **치명 1건, 중요 5건, 사소 1건**이다. 가장 직접적인 거짓 충족 경로는 새 `--documents`가 계약상 문서 수와 중복을 검사하지 않고, 공식 집계도 주어진 목록이 비어 있지 않기만 하면 그 일부만으로 `met`을 낼 수 있다는 점이다. D5 원격 태그 관문은 아직 `d4-registered`에 고정돼 있어 정상적인 D5 실행은 반대로 막힌다.

D4의 공식 파일과 공식 수치는 바뀌지 않았다. HEAD 도구로 D4 저장 보고서를 다시 집계하면 세 호출의 10칸이 L1에서 맞음으로 바뀌지만, 이는 D5 계약 3절과 D4 결과 보고서 5절에 실질적으로 밝혀져 있고 네 묶음은 모두 미충족 그대로다.

## 고정(④) 전에 반드시 고칠 것

### 1. [치명] D5 문서 목록이 일부이거나 중복이어도 공식 `met`이 가능하다

- 위치: `eval/d4_eval/run_d4.py:48-69,107-126`, `eval/d4_eval/official_d4.py:199-210,213-245`, `tests/test_d4_run.py:77-85,189-194`, `docs/EVAL_CONTRACT_D5.ko.md:50-53,88`
- 문제:
  - 실행기는 전달받은 JSON 안의 문서만 순회한다. 계약에서 정한 회사 수, 서로 다른 회사·PDF인지, `key`·순번·고유번호·원본 해시가 중복되지 않는지를 검사하지 않는다.
  - 공식 집계의 `bundle()`은 엔트리가 한 개만 있어도 모든 기준 합계가 0이면 `met`을 낸다. `documents` 수는 출력에 적을 뿐 판정 조건이 아니다.
  - 새 시험은 임의의 두 문서 목록이 실행기에 받아들여지고 그 해시가 기록되는지만 확인한다. D5 계약상 10곳이 모두 있어야 한다는 관문은 시험하지 않는다.
  - `documents_sha256`은 실행기와 집계기가 **같은 목록**을 읽었음을 보장한다. 그 목록이 등록된 완전한 D5 표본인지는 보장하지 않는다.
- 거짓 충족 경로: 10곳을 결정했는데 `eval/d5_eval/documents.json`에 9곳만 들어가거나 한 회사를 두 번 넣은 채 등록·실행하면, 남은 호출이 모두 0일 때 일부 표본으로 공식 `met`이 나온다. 이는 계약 5절의 “3.1은 10개, 3.3은 30개 모두”와 다르다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  import sys
  from pathlib import Path
  sys.path.insert(0, str(Path('eval/d4_eval').resolve()))
  from official_d4 import bundle, CRITERIA
  print(bundle([{'official_ready': True, 'key': 'only-one'}], CRITERIA['3.1']))
  PY
  ```

  결과는 `calls: 1`, `documents: 1`, `verdict: met`, `provisional: false`였다. 또한 `tests.test_d4_run`의 새 D5 경로 시험은 두 문서·16호출을 성공으로 받는다.
- 가장 작은 수정:
  1. 문서 목록에 사용자 결정으로 확정한 `expected_documents`를 넣고 등록한다.
  2. 실행기·위치 검사·공식 집계가 함께 쓰는 검증 함수에서 문서 수, `key`·`rank`·`corp_code`·텍스트 PDF 해시의 유일성, 세 스캔 조건, 저장소 안의 등록 상대경로를 검사한다.
  3. 공식 집계는 방식마다 텍스트 호출이 정확히 N개, 스캔 호출이 정확히 3N개가 아니면 `not official`이어야 한다.
  4. 0개·1개·N-1개·중복 key·중복 PDF/고유번호의 거부 시험과 D4 기본 10개 통과 시험을 더한다.

### 2. [중요] ④의 평가 도구 T에 이번에 바꾼 실행기·위치 검사·공식 집계가 들어가지 않는다

- 위치: `eval/d4_preflight.py:38-40,80-88,156-161`, `docs/EVAL_CONTRACT_D5.ko.md:21,24-26,46`
- 문제: D5 계약은 `run_d4.py`, `position_check.py`, `official_d4.py`를 평가 도구 변경으로 명시하고 ④에서 T를 고정한다고 한다. 그러나 `TOOL_PATHS`에는 핵심 다섯 파일만 있고 이 세 파일은 없다. 현재 관문에서는 이 세 도구가 D5 PDF·정답을 본 뒤인 ⑦에서야 등록된다. 따라서 “④ 뒤에는 평가 도구를 바꾸지 않는다”는 계약을 사전점검이 확인하지 못한다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  from eval.d4_preflight import TOOL_PATHS
  print(*TOOL_PATHS, sep='\n')
  PY
  ```

  결과는 `eval/d4_gold.py`, `eval/d4_score.py`, `eval/d4_candidates.py`, `eval/d4_preflight.py`, `eval/d4_scan.py`뿐이었다.
- 가장 작은 수정: D5의 T 경로 목록에 `eval/d4_eval/run_d4.py`, `eval/d4_eval/position_check.py`, `eval/d4_eval/official_d4.py`를 포함하고, 고정 기록과 사전점검이 세 객체도 대조하게 한다. D4 기본값을 유지하려면 `freeze --tool-paths ...`처럼 명시적 목록을 받게 해도 된다. 등록 시험뿐 아니라 freeze 객체 시험을 추가한다.

### 3. [중요] D5 원격 태그 관문이 구현되지 않아 정상 실행이 통과할 수 없다

- 위치: `eval/d4_preflight.py:117,129,147-154,189-200`, `docs/EVAL_CONTRACT_D5.ko.md:4,10,13`
- 문제: 로컬 HEAD 대조에는 CLI의 `--registered d5-registered`가 쓰이지만, 원격 조회는 상수 `TAG = "d4-registered"`만 쓴다. D5 절차가 `--registered d5-registered --remote origin`을 써도 원격에서는 D4 태그를 검사한다. D4 태그를 D5 R로 옮기지 않는 한 D5 사전점검은 실패하며, 태그를 옮기면 D4 공개 기록 원칙을 훼손한다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  from eval.d4_preflight import TAG
  print(TAG)
  PY
  ```

  결과는 `d4-registered`였다. 원격 조회와 메시지도 이 상수를 직접 쓴다.
- 가장 작은 수정: `check()`와 CLI에 `--tag`를 추가하고 기본값을 `d4-registered`로 둔다. 로컬 `--registered`, 원격 태그 조회, 로그 문구에 같은 값을 쓰게 한다. D5 절차는 `--registered d5-registered --tag d5-registered`를 고정한다. D4 기본 태그와 D5 지정 태그를 각각 확인하는 시험을 둔다.

### 4. [중요] 점 날짜 정규식은 기간 줄이 아닌 문장·행까지 잡는다

- 위치: `eval/d4_gold.py:50-54,92-100,130-141`, `tests/test_d4_tools.py:534-556`
- 확인된 범위: D4 PDF 10개에서 새 점 날짜 대안만 새로 잡은 줄은 DSR의 12줄이었다. 7·9·10·11·12쪽의 재무제표 기간 머리글 10줄과 13쪽의 반복 기간 머리글 2줄로, D4에서 의도하지 않은 줄은 없었다.
- 문제: `DATED`는 줄 전체 형식을 확인하지 않고 어디서든 `YYYY.MM.DD 현재|부터|까지`가 있으면 맞는다.
  - `statements_of()`는 제목 뒤 네 줄 안의 설명문에 이 문자열이 있어도 재무제표 시작으로 인정한다.
  - `_line_kind()`는 쉼표 묶음 금액이 없는 날짜 포함 행을 곧바로 `drop`한다. 작은 금액이나 쉼표 없는 금액이 든 실제 행이면 `ungrouped_amount`·사람 매핑으로 가지도 않는다. OpenDART 대응값도 없으면 정답에서 조용히 사라져 제품이 같이 놓쳤을 때 거짓 충족에 기여할 수 있다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  # eval.d4_gold의 DATED, _line_kind, statements_of에 손으로 만든 줄을 넣음
  # "2025.12.31 현재 보증금 47"
  # 제목 뒤 "2025.12.31 현재 계약조건을 검토했다"
  PY
  ```

  실제 결과는 각각 `DATED True, line_kind drop`과, 설명문을 기간 줄로 삼아 `연결재무상태표@1` 블록을 만든 것이었다.
- 가장 작은 수정: “날짜 조각” 정규식과 “재무제표 기간 줄 전체” 정규식을 나눈다. 후자는 `fullmatch`에 가까운 형태로 `제 N 기/기말`, 한두 개의 날짜, `현재/부터/까지`, 허용 구두점 외의 계정·설명 문자가 없는 줄만 받게 하고 두 호출부가 이를 쓴다. 날짜가 든 설명문과 날짜가 든 작은 금액 행이 각각 블록 시작·`drop`이 되지 않는 회귀 시험을 추가한다.

## 계약에 적을 것

### 5. [중요] 포괄 치환 규칙과 실제 D5 파일 배치가 충돌하며 후보 기록 경로도 빠져 있다

- 위치: `docs/EVAL_CONTRACT_D5.ko.md:4,13,46,50-55,80-84`, `docs/EVAL_CONTRACT_D4.ko.md:50-80,236-246,307-327`, `docs/D4_RUN_PROCEDURE.ko.md:39-50,154-158`
- 문제:
  - 4행의 `eval/d4_eval/` → `eval/d5_eval/` 포괄 치환은 실행 스크립트까지 `eval/d5_eval/run_d4.py` 등으로 옮긴다는 뜻이 된다. 그러나 이번에 검토한 코드는 `eval/d4_eval/`에 남아 있고 D5 데이터만 `--documents`·`--places`로 받는 설계다.
  - `eval/d5_eval/documents.json`, `eval/d5_eval/duplicate_places.json`, gold·mapping·scan map·결과 폴더의 정확한 목록과 각 CLI의 정확한 인자가 계약에 없다.
  - 20~30번의 원본은 `eval/d4_candidates/`에 있다. 새 첨부 기록과 31번 이후 기록을 어디에 둘지 정하지 않았다. D4 파일을 고치면 D4 기록을 건드리고, 별도 파일로 두되 등록 목록에서 빠뜨리면 D5 선정 근거가 R에 묶이지 않는다.
- 근거 명령과 결과:

  ```bash
  git diff --name-status 14b853c..d5-tools
  find eval/d4_eval -maxdepth 2 -type f | sort
  ```

  변경된 세 스크립트는 모두 `eval/d4_eval/`에 있고 현재 `eval/d5_eval/`은 없다. D4 등록 기록에는 D4 후보 1~30, 문서 목록, 정답·매핑, 스캔 map, 66자리, 세 공식 스크립트가 명시돼 있다.
- 가장 작은 수정: 포괄 치환을 없애고 D5 파일 표를 계약에 둔다.
  - 공유 코드: `eval/d4_gold.py`, `eval/d4_score.py`, `eval/d4_candidates.py`, `eval/d4_preflight.py`, `eval/d4_scan.py`, `eval/d4_eval/{run_d4.py,position_check.py,official_d4.py}`
  - D5 데이터: `eval/d5_candidates/`, `eval/d5_excluded.json`, `eval/d5_eval/documents.json`, `gold/`, `scans/`, `duplicate_places.json`, 결과 경로
  - 기록: `eval/freeze_d5.json`, `eval/register_d5.json`, `docs/D5_RUN_PROCEDURE.ko.md`
  - 20~30번은 D4 파일을 수정하지 말고 D5 후보 파일로 복사하되 원본 경로·git 객체 또는 SHA-256·받은 시각을 남긴다. 새 첨부 이름은 D5 파일에만 기록한다.
  - ⑦의 정확한 `register --paths`와 ⑧·⑨의 `--documents`·`--places` 명령을 계약 또는 등록되는 절차서에 적는다.

### 6. [중요] 고정 전 제품·환경 변경 범위가 열려 있고 개발 결과에 따른 선택 이력이 남지 않는다

- 위치: `docs/EVAL_CONTRACT_D5.ko.md:17-22`, `docs/EVAL_PLAN_D5.ko.md:3,30-36,60-65`
- 문제: 제품 P는 `5cdb4e1`, `180e621` 외에 “그 뒤 개발 측정에서 나오는 수정”을 제한 없이 포함할 수 있다. 모델·프롬프트·OCR·기계도 “다르면 기록·보고”만 하면 된다. ④의 최종 커밋·환경 해시는 남지만, 어떤 개발 입력과 결과를 보고 후보 버전·환경 중 하나를 골랐는지와 버린 후보는 남지 않는다.
- 범위 판단: D4 계약을 상속하므로 D5 후보 PDF를 열기 전 ④ 고정이라는 장벽은 있다. 따라서 **D5 실행 결과를 본 뒤 P를 바꾸는 재량**은 계약상 없다. 남은 문제는 D4 개발 측정 결과를 본 뒤의 변경·버전 선택 범위와 이력이 열려 있다는 것이다.
- 근거 명령과 결과:

  ```bash
  nl -ba docs/EVAL_CONTRACT_D5.ko.md | sed -n '15,23p'
  nl -ba docs/EVAL_PLAN_D5.ko.md | sed -n '30,36p;60,66p'
  ```

  계약은 향후 수정을 허용하고, 계획은 AI 개발 측정 결과를 본 뒤 더 고칠 수 있다고 적는다. 변경 허용 범위·개발 문서 목록·후보 버전 기록 의무는 없다.
- 가장 작은 수정: ④ 전에 최종 계약의 P 절을 닫힌 목록으로 바꾼다. 허용한 제품 커밋, 각 수정 이유, 사용한 개발 문서·측정 폴더와 결과, 선택하지 않은 후보 버전을 기록한다. 추가 수정이나 모델·프롬프트·OCR 변경은 계약 개정과 같은 범위의 재검토를 거치게 하고, D5 후보·PDF·재무제표 캐시는 F 전 열거나 실행하지 않는다고 명시한다.

### 7. [사소] DSR 재현 문구는 문자 그대로의 계정명 일치가 아니며 확인 코드를 브랜치 이름으로만 가리킨다

- 위치: `docs/EVAL_CONTRACT_D5.ko.md:37-45`
- 문제: 새 DSR 정답 211칸은 사람이 적은 212칸과 `label_key` 기준으로는 모두 대응하지만, 원문 계정명 문자열이 모두 같지는 않다. 여섯 칸은 “지정된유동/지정된비유동”, “포괄손익에대한”처럼 사람이 넣은 공백 때문에 문자열이 다르다. 또한 `d5-tools`는 움직일 수 있는 브랜치 이름이다.
- 근거 명령과 결과: 새 정답과 D4 수동 `add_statement` 칸을 `(statement_id, page, label_key(label), period, printed)` 다중집합으로 비교하면 교집합 211, 새 정답만 0, 수동 정답만 이익잉여금 당기 1칸이었다. 원문 label로 비교하면 교집합은 205였다.
- 가장 작은 수정: “211칸은 D4 채점의 계정명 정규화(`label_key`)·기간·인쇄값 기준으로 같다”로 고치고, 확인 코드 커밋 `1547a2c` 또는 최종 T 해시를 적는다.

## 요청 항목별 재현·판단

### D4 정답 10개 재생성

사용 명령의 형태:

```bash
PY=~/Documents/ChatGPT/dart-review-agent/.venv/bin/python
$PY eval/d4_gold.py --pdf ~/Desktop/D4/<문서>.pdf --corp-code <고유번호> \
  --cache ~/Documents/ChatGPT/dart-review-agent/cache/d4 --out /tmp/<문서>.gold.json
```

- 10개 중 DSR을 뺀 9개는 저장된 `.gold.json`과 바이트 단위로 같았다.
- DSR은 4개 재무제표를 `연결재무상태표@7`, `연결손익계산서@9`, `연결포괄손익계산서@10`, `연결현금흐름표@12`로 찾았고 쪽 범위·단위가 수동 기록과 같았다.
- 자동 칸 211개는 수동 212개 중 211개와 `label_key`·기간·인쇄값 기준으로 같았다.
- 남은 수동 칸은 8쪽 이익잉여금 당기 `219,722,694,808`이다. 새 생성 결과에는 `8` 줄의 `no_label`과 같은 값의 `dart_only`가 남았다.
- 포괄손익의 OpenDART 값 네 개도 `dart_only`로 남았다.

### D4 공식 저장 보고서 80개 재집계

```bash
python3 eval/d4_eval/official_d4.py \
  --run eval/d4_eval/results/2026-10-20/run1 \
  --judgments eval/d4_eval/results/2026-10-20/judgments/run1 \
  --documents eval/d4_eval/documents.json \
  --places eval/d4_eval/duplicate_places.json
```

바뀐 호출과 칸:

| 호출 | 맞음 | L1 |
|---|---:|---:|
| `17_00759294.blur.ai` | 73 → 75 | 2 → 0 |
| `19_00164788.text.rules` | 206 → 210 | 4 → 0 |
| `19_00164788.text.ai` | 204 → 208 | 4 → 0 |

다른 77개 호출은 객체 수준의 수치가 같았고, 80개 모두 `official_ready`였다. 새 묶음 수치는 다음과 같았다.

| 묶음 | 새 수치 | 판정 |
|---|---|---|
| 규칙 텍스트 | S1 0, L1 0, S2 1 | 미충족 |
| 규칙 스캔 | S1 3, L1 2, S2 6652 | 미충족 |
| AI 텍스트 | S1 11, L1 4, S2 0 | 미충족 |
| AI 스캔 | S1 27, L1 0, S2 5559 | 미충족 |

### 계정명 정규화와 위치 66곳

- 확정 매핑을 적용한 D4 정답에서는 기존 `label_key`와 새 `label_key`가 달라지는 칸이 0개였고, 새 key가 서로 다른 기존 key를 합친 자리도 0개였다.
- 저장 보고서에서는 다섯 행·10칸만 key가 달라졌다. 현대모비스 텍스트 규칙·AI의 끝 콜론 네 행·8칸과 와이솔 blur AI의 가운뎃점 한 행·2칸이다. 같은 재무제표 안에서 서로 다른 기존 계정을 새 key 하나로 합친 경우는 없었다.
- 위치 검사를 현재 코드로 다시 만들면 `the same: 66 places of 10 documents`였다. 새 정규화 때문에 D4 등록 자리 id가 늘거나 줄지 않았다.
- 일반적으로 끝 콜론이나 가운뎃점 코드만 다른 두 행은 이제 같은 key가 된다. 이는 의도한 동치다. 그런 행이 한 재무제표에 실제로 둘 있으면 위치 검사가 중복 자리로 등록하고 순서를 검사하므로, D5 등록 전 `verify`가 반드시 통과해야 한다.

### D4 기본 동작과 새 경로 인자

- D4 기본 `run_d4.py --dry-run` 결과는 `80 calls; inputs match the registered documents; nothing was run`이었다.
- 기본·명시적 D4 `position_check.py verify`는 모두 66곳이 같았다.
- `official_d4.py`에 D4 `--documents`·`--places`를 명시한 재집계는 위 수치와 같았다.
- 관련 시험은 제품 호출을 가짜로 바꾸는 `tests.test_d4_run`, 손제작 입력을 쓰는 `D5ToolChangeTests`, 위치 검사 시험만 실행했다. 결과는 **45개 통과**였다.
- 따라서 경로 인자 자체와 `documents_sha256`의 실행기↔집계기 대조는 동작한다. 발견 1은 그 해시가 목록의 완전성·유일성까지 뜻하지 않는다는 문제다.

### 회사 선정과 2026-10-15 기록 재사용

- 순번 20에서 시작해 같은 규칙으로 포함 N곳에서 멈추는 규칙은 계약 확정 뒤에는 결정적이다. D5 결과를 본 뒤 회사를 교체할 재량은 없다.
- 다만 “회사를 고를 재량이 없다”는 표현은 너무 강하다. 20~30번의 회사명·업종·공시 목록은 2026-10-15에 이미 받아 두었고, 20번은 첨부 이름도 한 번 기록돼 있다. D5를 만들 때 이 후보들의 정체와 기초 메타데이터는 알려져 있었다. 또한 재사용과 재조회 중 무엇을 택할지는 서로 다른 회사 집합을 만들 수 있는 사전 선택이다.
- 이 기록을 다시 쓰는 것 자체는 문제가 아니다. 조회 기간이 닫힌 2026-01-01~06-30이고 받은 시각이 있으며, 이미 고정된 스냅샷을 재사용하는 편이 시간 경과에 따른 입력 변경을 줄인다. 단, ③에서 **새 조회나 PDF 열람 전에** 재사용/재조회를 확정하고, 위 5번처럼 D5 후보 기록에 원본 해시와 출처를 남겨야 한다. 재조회하면 구기록과 신기록의 차이, 그 차이로 후보 판정이 바뀌었는지를 모두 보고해야 한다.

### 5절 사람 판정 기준

- D4 4.3의 맞음 정의인 같은 재무제표·계정명·기간·값과 모순되지 않고, D4 4.5의 `ok`/`wrong`을 실행 전에 구체화한다.
- 재량을 더 줄이려면 “재무제표”는 단순히 제목이 같은 시트가 아니라 정답의 특정 재무제표 id에 대응하는 인쇄 표, “계정명”은 D4 4.3의 `label_key`, “기간”은 인쇄된 그 열이라고 한 문장을 보태는 것이 좋다. 판정 note에는 PDF 쪽·인쇄 행·기간 머리글·인쇄 금액을 적게 한다.

### 6절 제목 미확인 표

- 현재 코드에서 거짓 충족 경로는 재현되지 않았다. 제목은 정확히 `제목 미확인 표`이고 모든 생성 칸은 `확인 필요`가 된다(`dart_review/documents/statement.py:134-135,286-300`, `dart_review/documents/verify.py:94-96`).
- 채점기는 제목과 쪽 범위가 같은 제품 재무제표만 정답에 짝짓는다(`eval/d4_score.py:160-170`). 따라서 제목 미확인 표는 짝이 되지 않고 그 칸은 표시된 정답 밖 칸, 해당 정답 칸은 빠짐이다.
- 제목 미확인 표 내부의 문제 문장은 짝이 없는 정답 재무제표의 `problems`로 옮겨지지 않는다. `UNTITLED_REASON`에는 쪽·행·기간·인쇄 금액도 없어 D4 4.4의 포인터가 아니다. 그러므로 텍스트 PDF의 빠진 칸은 가리켜진 것으로 줄지 않고 S2가 된다.
- 이 성질은 계약과 일치한다. 회귀를 막으려면 손제작 보고서로 “제목 미확인 표의 모든 칸이 표시됨, 정답 칸은 S2, 내부 문제 문장은 포인터가 아님”을 직접 시험하는 것이 좋다.

### D4와의 관계

- `git diff 14b853c..d5-tools -- docs/EVAL_CONTRACT_D4.ko.md eval/d4_eval/results/2026-10-20`은 비어 있었다. D4 계약과 공식 기록은 수정되지 않았다.
- D4 결과 보고서 5절은 도구 간 불일치 10칸과 이를 뺀 네 묶음의 판정을 이미 적고 있다. D5 계약 3절은 HEAD 계열 도구의 재집계에서 정확히 세 호출·10칸만 바뀌고 공식 D4는 R 도구 결과로 둔다고 적는다. 공개 설명은 내용상 충분하다.
- 다만 7번처럼 재현 도구를 움직이는 브랜치명이 아니라 커밋/T 해시로 고정해야 한다. D4 공식 수치와 HEAD 재집계 수치를 결과 문서에서 계속 명확히 구분해야 한다.
