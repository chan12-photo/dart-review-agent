# Codex 4차 검토 요청: D4 계약 4판과 3차 지적 수정 (필수, 2026-10-11)

- 사용 방법: 이 저장소 폴더에서 Codex를 열고 아래 요청문을 붙여 넣는다. 결과는 `docs/reviews/D4_fourth_codex_result.ko.md`로 저장한다.
- 이 검토를 반영하고 사용자 결정(계약 10절)을 받은 뒤에 ④ 고정을 한다. 그 전에는 평가 문서를 열거나 내려받지 않는다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama는 쓰지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D4_fourth_codex_result.ko.md`에 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다. 틀렸거나, 근거가 약하거나, 결과를 실제보다 좋게 보이게 하는 것만 적어 줘. 발견마다 다음을 적어 줘.
- 심각도(치명/중요/사소)
- 위치(파일:줄)
- 근거(명령과 결과)
- 제안
- 분류: "④ 고정 전에 고칠 것" 또는 "기록만 할 것"

대상은 `009fdc1..HEAD`이다. 3차 결과는 `docs/reviews/D4_third_codex_result.ko.md`, Claude의 응답은 `docs/reviews/D4_third_codex_response.ko.md`에 있다.

### Part A. 3차 지적이 막혔는가

1. 3차 결과 마지막 절의 재현 입력 두 개를 지금 코드로 다시 돌려 줘. 바뀐 형식은 다음과 같다. 같은 종류의 다른 반례가 남았는지 봐 줘.
   - 판정 파일: `report_sha256`, `judged_by`, `verdicts`의 id → `{"verdict", "note"}`
   - 매핑표: `status`, 항목마다 다른 `note`
   - 제품 보고: 기간이 든 "AI가 읽지 않았다", 행 이름을 따옴표로 넣은 "표에 넣지 못한 금액"
2. **가리킴** (1번, `eval/d4_score.py`의 `UNREAD`, `ORPHANS`, `ORPHAN`, `pointers`, `covered`): 맞는 보고를 못 가리키거나 틀린 보고가 가리키는 경우를 찾아 줘.
   - 계정명에 쉼표·괄호·작은따옴표가 든 경우
   - "외 N개"로 줄인 목록, 행 이름 없는 보고
   - "3번째 기간"처럼 세 번째 기간 열의 보고
   - 같은 행 이름이 한 쪽에 두 번 있는 경우, 재무제표가 두 쪽에 걸친 경우
3. **정답 밖 칸** (2번): 칸 id("재무제표 순번/행 순번/열")가 저장된 보고서 안에서 칸 하나를 정확히 가리키는가. 짝 없는 제품 재무제표, 세 번째 기간 열, 찾지 못한 재무제표(이제 S2)의 처리가 계약 4.4·4.5와 같은가.
4. **정답 생성기** (3번, `eval/d4_gold.py`):
   - `_is_heading`과 `HEADING`, `PAGE_NUMBER`, `no_grouped_amounts`, `statement_not_found`(손익·포괄손익을 하나로 봄)가 반대로 실제 행을 버리거나, 머리글·바닥글을 정답 칸으로 만드는가.
   - `statement_not_found`가 별도(OFS) 재무제표는 보지 않는 것이 맞는가.
5. **매핑표 검사** (5번, `apply_mapping`, `_checked_cell`): 사람이 실수로 정답을 망가뜨리는 길이 남았는가. 예: 단위, 부호, 같은 자리 판정(띄어쓰기만 지운 계정명), `drop`과 `add`의 순서.
6. **분모와 짝짓기** (6번, 그리고 Claude가 덧붙인 짝짓기 순서): "-" 칸에 값(`dash_filled`), 같은 값을 먼저 짝짓고 같은 쪽을 먼저 쓰는 순서가 오히려 다른 칸을 잘못 맞음으로 만드는 경우.
7. **제품** (4·7번과 기록 10):
   - `statement.py` `_set_note_columns`: 위 머리글로 열을 정하는 규칙. 머리글이 다른 쪽에 있거나 멀리 있는 경우, 불확실 열 표시.
   - `verify.py` `_trusted_structure`, `sums_uncertain`: 층을 너무 믿거나 너무 안 믿는 경우. 개발 측정에서 포스코 55칸, 한화시스템 16칸의 맞는 값이 표시된다.
   - `ai_reader.py` `_in_free_slot`, `_period_edges`: 주석 번호를 금액으로 보거나 실제 작은 금액을 버리는 경우.
8. **고정과 사전 점검** (8번, `eval/d4_preflight.py`): 실행이 고정된 것과 다른데도 점검을 통과하는 길. 예: 무시되는 파일(`.gitignore`), 환경 변수, 모델 서버 설정, worktree 밖의 파일.
9. **후보 규칙** (9번, `eval/d4_candidates.py`): 사람이 결과를 보고 고를 틈이 남았는가. 정정·첨부추가 공시, 첨부 이름, 글자 수 기준(1,000자, 절반의 쪽)이 텍스트 PDF를 부당하게 빼거나 스캔을 넣는가.
10. **합성 스캔** (`eval/d4_scan.py`, 새 도구): 쪽 고르기(정답 재무제표의 쪽 범위), 조건, 결정성, 정답 쪽 번호 바꾸기(`scan_gold`, `--page-map`)의 결함. 개발 PDF 하나로 실제로 만들어 보고 쪽 수와 대응표를 확인해 줘(만든 파일은 커밋하지 않는다).

### Part B. 계약 4판 (`docs/EVAL_CONTRACT_D4.ko.md`)

1. 1.1~1.2(고정·사전 점검)가 "결과를 보고 고치는" 틈을 막는가. 남은 틈이 있으면 실행 가능한 검사로 제안해 줘.
2. 3.2(후보 판정)의 각 단계가 기계적인가. 사람이 판단하는 곳이 남았으면 적어 줘.
3. 4.3~4.5와 5절의 정의가 채점기 구현과 같은가. 다른 곳이 있으면 어느 쪽을 고쳐야 하는가.
4. 5절의 상태(기계 채점 완료 / 사람 확인 완료 / 공식 판정 가능)가 개발 기록과 공식 보고에서 오해 없이 쓰이는가.

### Part C. 개발 측정 (`eval/documents_2026-10-11_after-third/`)

1. `REPORT.ko.md`의 숫자와 주장이 `rules.json`, `ai.json`, `d4_dev/*.score.json`, `reports/*.report.json`과 맞는가. 결과를 좋게 보이게 하는 표현이 있는가.
2. `d4_dev/*.mapping.json`(`draft`, 사용자 확인 전)의 항목별 근거를 표본으로 원본 PDF의 글자 층과 대조해 줘. `~/Desktop/감사보고서/`에 있는 `eval/measure_documents.py` `DOCUMENTS`의 6개 파일만 쓴다. 근거의 계산(합·차)이 맞는지도 봐 줘.
3. 저장된 보고서로 채점을 다시 돌려 같은 결과가 나오는지 확인해 줘:
   - `.venv/bin/python eval/d4_score.py --report eval/documents_2026-10-11_after-third/reports/<이름>.<rules|ai>.report.json --gold eval/documents_2026-10-11_after-third/d4_dev/<이름>.gold.json --mapping eval/documents_2026-10-11_after-third/d4_dev/<이름>.mapping.json --out /tmp/s.json`
4. 규칙 방식 측정을 다시 돌려 저장된 기록과 같은지 확인해 줘:
   - `.venv/bin/python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out /tmp/d4fourth --reports /tmp/d4fourth/reports`

## 이미 알고 있는 것 (다시 적지 않아도 됨)

- 자본변동표는 읽지 않는다(문제로만 표시). 사진 PDF는 규칙 방식으로 읽지 못한다.
- 사진 경로:
  - 띠 실패는 포괄 메시지만 남는다.
  - 세 자리 OCR 숫자는 "AI가 읽지 않았다"로 보고하지 않는다.
  - 계정명을 확인하지 못한 칸은 메모만 있고 "확인 필요"가 아니다.
- 개발 측정과 개발 정답은 개발에 쓴 문서라 평가가 아니다. 정답 생성기와 제품은 같은 글자 층을 읽는다.
- 가리킴 규칙은 제품에 불리한 쪽으로 엄격하다(계약 4.4, 9절).
- 손익·포괄손익계산서는 제품이 검산하지 않는 종류다(A4에서 따로 센다).
- 기록 10의 수정은 함수 수준 테스트로만 확인했다(실제 모델을 쓰는 전체 경로 회귀 없음).
