# Codex 5차 검토 요청: D4 계약 5판과 4차 지적 수정 (필수, 2026-10-11)

- 사용 방법: 이 저장소 폴더에서 Codex를 열고 아래 요청문을 붙여 넣는다. 결과는 `docs/reviews/D4_fifth_codex_result.ko.md`로 저장한다.
- 이 검토를 반영하고 사용자 결정(계약 10절)을 받은 뒤에 ④ 고정을 한다. 그 전에는 평가 문서를 열거나 내려받지 않는다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama는 쓰지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D4_fifth_codex_result.ko.md`에 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다. 틀렸거나, 근거가 약하거나, 결과를 실제보다 좋게 보이게 하는 것만 적어 줘. 발견마다 다음을 적어 줘.
- 심각도(치명/중요/사소)
- 위치(파일:줄)
- 근거(명령과 결과)
- 제안
- 분류: "④ 고정 전에 고칠 것" 또는 "기록만 할 것"

대상은 `7729a80^..HEAD`이다. 4차 결과는 `docs/reviews/D4_fourth_codex_result.ko.md`, Claude의 응답은 `docs/reviews/D4_fourth_codex_response.ko.md`에 있다.

### Part A. 4차 지적이 막혔는가

1. 4차 결과의 반례를 지금 코드로 다시 돌려 줘. 같은 종류의 다른 반례가 남았는지 봐 줘. 바뀐 형식은 다음과 같다.
   - `statement_not_found`의 결정: `add_statement`, `same_statement`, `unscorable`
   - 정답·보고서의 `source.sha256`, `source_sha256`
   - 등록 기록(`register`)과 점검 인자(`--register`, `--registered`, `--remote`)
2. **등록 커밋 R** (`eval/d4_preflight.py` `register_record`, `check`): 등록과 다른 정답·매핑표·대응표로 실행해도 점검을 통과하는 길이 남았는가. 예: 등록하지 않은 파일이 실행에 쓰이는 경우, 태그의 종류(가벼운 태그·주석 태그), 원격 이름. 태그를 옮겨 다시 push하는 것은 계약 1.2에 한계로 적었다.
3. **정답 생성기** (`eval/d4_gold.py`):
   - `UNGROUPED`·`ungrouped_amount`가 연도("2025")나 쪽 번호를 금액으로 보내 항목을 쏟아내거나, 반대로 쉼표 없는 금액을 놓치는가.
   - `add_statement`·`same_statement`·`unscorable` 검사의 빈틈. 예: 사람이 적은 재무제표의 쪽 범위가 다른 재무제표와 겹치는 경우.
4. **매핑표 검사** (`_checked_cell`, `_place`): 원 단위는 "주당" 행과 사람이 `"row_unit": "원"`이라고 적은 칸만 받는다. 이 예외가 다시 잘못된 값을 들이는 길이 되는가, 아니면 실제 원 단위 행을 막는가.
5. **채점기** (`eval/d4_score.py`): 부호 비교(`negative`), 세 번째 짝짓기 단계의 같은 쪽 우선, 원본 해시 검사(`source_verified`, 다른 PDF 거부), `scorable`이 공식 판정을 막는 방식.
6. **스캔** (`eval/d4_scan.py`): `expand=True`로 쪽 크기가 바뀌는 것이 제품의 읽기(쪽 높이에 기대는 규칙 등)에 영향을 주는가. `scan_gold`의 대응표 검사가 충분한가.
7. **제품** (`dart_review/documents/verify.py` `_trusted_structure`, `ai_reader.py` `_in_free_slot`):
   - 들여쓰기를 요구한 층 규칙이 실제로 들여 쓴 표에서 틀린 층을 만들거나, 너무 많은 맞는 칸을 표시하는가.
   - "열 위치를 모르는 기간의 작은 숫자도 읽지 않았다고 보고"가 거짓 경고를 얼마나 늘리는가. 반대로 여전히 조용히 빠지는 경로가 남았는가.
8. **후보 선택** (`eval/d4_candidates.py select`): 기록한 입력만으로 판정이 끝까지 정해지는가. 사람이 끼어들 틈이 남았는가.

### Part B. 계약 5판 (`docs/EVAL_CONTRACT_D4.ko.md`)

1. 1.2(등록과 점검)의 절차가 실행 가능하고, 결과를 보고 고치는 틈을 막는가.
2. 4.2의 `statement_not_found` 결정과 5절의 상태(`scorable`, `source_verified`)가 구현과 같은가.
3. 그 밖에 계약과 구현이 다른 곳.

### Part C. 개발 측정 (`eval/documents_2026-10-11_after-fourth/`)

1. `REPORT.ko.md`의 숫자와 주장이 `rules.json`, `ai.json`, `d4_dev/*.score.json`, `reports/*.report.json`과 맞는가. 결과를 좋게 보이게 하는 표현이 있는가.
2. 저장된 보고서로 채점을 다시 돌려 같은 결과가 나오는지 확인해 줘:
   - `.venv/bin/python eval/d4_score.py --report eval/documents_2026-10-11_after-fourth/reports/<이름>.<rules|ai>.report.json --gold eval/documents_2026-10-11_after-fourth/d4_dev/<이름>.gold.json --mapping eval/documents_2026-10-11_after-fourth/d4_dev/<이름>.mapping.json --out /tmp/s.json`
3. 규칙 방식 측정을 다시 돌려 저장된 기록과 같은지 확인해 줘. `~/Desktop/감사보고서/`에 있는 `eval/measure_documents.py` `DOCUMENTS`의 6개 파일만 쓴다:
   - `.venv/bin/python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out /tmp/d4fifth --reports /tmp/d4fifth/reports`

## 이미 알고 있는 것 (다시 적지 않아도 됨)

- 자본변동표는 읽지 않는다(문제로만 표시). 사진 PDF는 규칙 방식으로 읽지 못한다.
- 사진 경로: 띠 실패는 포괄 메시지만 남는다. 세 자리 OCR 숫자는 "AI가 읽지 않았다"로 보고하지 않는다. 계정명을 확인하지 못한 칸은 메모만 있고 "확인 필요"가 아니다.
- 개발 측정과 개발 정답은 개발에 쓴 문서라 평가가 아니다. 정답 생성기와 제품은 같은 글자 층을 읽는다.
- 가리킴 규칙은 제품에 불리한 쪽으로 엄격하다(계약 4.4, 9절).
- 손익·포괄손익계산서는 제품이 검산하지 않는 종류다(A4에서 따로 센다).
- 태그를 옮겨 다시 push하는 것은 점검으로 막지 못한다(계약 1.2).
- 4차 12번의 첫 반례(주석 번호가 전기 금액 열과 같은 x)는 고치지 않았고, 전체 경로 회귀가 없다(응답 2절).
