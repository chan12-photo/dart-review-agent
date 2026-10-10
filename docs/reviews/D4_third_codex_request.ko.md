# Codex 3차 검토 요청: D4 계약 3판과 재검토 지적 수정 (필수, 2026-10-10)

- 사용 방법: 이 저장소 폴더에서 Codex를 열고 아래 요청문을 붙여 넣는다. 결과는 `docs/reviews/D4_third_codex_result.ko.md`로 저장한다.
- 이 검토를 반영하고 사용자 결정(계약 10절)을 받은 뒤에 ④ 고정(제품 P, 평가 도구 T, 모집단·순서)을 한다. 그 전에는 평가 문서를 열거나 내려받지 않는다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama는 쓰지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D4_third_codex_result.ko.md`에 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다. 틀렸거나, 근거가 약하거나, 결과를 실제보다 좋게 보이게 하는 것만 적어 줘. 발견마다 심각도(치명/중요/사소), 위치(파일:줄), 근거(명령과 결과), 제안을 적고, "④ 고정 전에 고칠 것"과 "기록만 할 것"을 나눠 줘.

대상은 `dad0c32..HEAD`이다. 재검토 결과는 `docs/reviews/D4_recheck_codex_result.ko.md`, Claude의 응답은 `docs/reviews/D4_recheck_codex_response.ko.md`에 있다.

### Part A. 재검토 지적이 막혔는가

1. 재검토 결과 마지막 절의 재현 명령 두 개를 지금 코드로 다시 돌려 줘. 채점기와 정답 생성기의 입력 형식이 바뀌었다(재무제표 `id`, 칸의 `statement_id`, "-" 칸의 `value: None`, 매핑표 `apply_mapping`, 정답에 없는 칸의 판정 `extras`). 바뀐 형식에 맞춰 같은 상황을 만들고, 이제 어떻게 되는지와 같은 종류의 다른 반례가 남았는지 봐 줘.
2. 1번(가리킴): `eval/d4_score.py`의 `pointers`, `pointed`, `AI_POINT`, `RULES_POINT`. 문제 문장의 다른 형식(여러 금액을 한 문장에 적은 규칙 방식의 "표에 넣지 못한 금액 N개 (…)", 쪽이 없는 문장), 계정명에 작은따옴표나 괄호가 들어간 경우, 같은 금액이 당기·전기에 함께 있는 경우에 잘못 가리키거나 못 가리키는가.
3. 2번(정답에 없는 칸): `extras` 판정 키(`statement_id|label|period|printed`)가 같은 행·기간의 두 칸을 구별하는가. `complete`가 거짓이면 공식 판정을 내지 않는다는 것이 계약과 도구에서 같은가.
4. 3번(정답 생성기): `_line_kind`의 "uncertain" 판정(쪽 높이의 92% 아래, 쉼표 있는 금액 없음, 한글 있음)이 반대로 실제 바닥글을 정답 칸으로 만들거나, 다른 위치의 작은 금액 행을 버리는 경우. `apply_mapping`의 결정 규칙(`keep/drop/ignore/add`)이 사람이 실수로 정답을 망가뜨리는 경로를 막는가(예: `add`로 이미 있는 칸을 한 번 더 넣기).
5. 5번(오른쪽 주석 열): `statement.py`의 `_set_note_columns`와 `verify.py`의 기간 머리글 검사(`PERIOD_MARK`). 금액이 작은 실제 열(모든 금액이 두 자리 이하인 열)이 주석 열로 잘못 갈리는가. AI 방식 `_in_free_slot`의 반례.
6. 6번(소계 구조): `verify.py`의 `_check_sum`, `_levels`, `_marker`, `_indent`. 항목 기호가 다르면 그 구조를 믿는 규칙이 틀린 층을 만드는 경우(예: 항목 기호가 일부 행에만 있는 표). 그대로의 합이 틀리고 층으로는 맞을 때 칸을 표시하는 새 규칙이 맞는 칸을 너무 많이 표시하는가(개발 측정의 한화시스템 16칸).
7. 10번(서버 잠금): `server.py`의 `_lock_data_dir`. 잠금이 풀리지 않는 경우(프로세스 비정상 종료), 테스트에서 잠금을 잡은 앱이 남는 경우.

### Part B. 계약 3판 (`docs/EVAL_CONTRACT_D4.ko.md`)

1. ④에서 P와 T를 고정하고 ⑧에서 diff를 확인하는 순서가 "결과를 보고 고치는" 틈을 막는가. 합성 스캔 코드와 시드를 T에 넣는 것이 충분한가.
2. 3.2 후보 판정 절차가 결과를 보고 후보를 고를 틈을 남기는가(사람이 PDF를 받는 단계, "열리지 않음"의 판정).
3. 4.3~4.5와 5절의 정의가 채점기 구현과 같은가. 다른 점이 있으면 어느 쪽을 고쳐야 하는가.
4. A4 정의와 "검산하지 못했다" 칸 표시의 관계가 분명한가.

### Part C. 개발 측정 (`eval/documents_2026-10-10_after-recheck/`)

1. `REPORT.ko.md`의 숫자와 주장이 `rules.json`, `ai.json`, `d4_dev/*.score.json`과 맞는가. 결과를 좋게 보이게 하는 표현이 있는가.
2. `d4_dev/*.mapping.json`(Claude 1차, 사용자 확인 전)의 결정 근거가 충분한가. 표본으로 몇 개를 원본 PDF의 글자 층과 대조해 줘(`~/Desktop/감사보고서/`의 `eval/measure_documents.py` `DOCUMENTS` 6개 파일만).
3. 규칙 방식 측정과 채점을 다시 돌려 같은 결과가 나오는지:
   - `.venv/bin/python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out /tmp/d4third`
   - `.venv/bin/python eval/d4_score.py --pdf <파일> --gold eval/documents_2026-10-10_after-recheck/d4_dev/<이름>.gold.json --mapping eval/documents_2026-10-10_after-recheck/d4_dev/<이름>.mapping.json --reader rules --out /tmp/s.json`

## 이미 알고 있는 것 (다시 적지 않아도 됨)

- 자본변동표는 읽지 않는다(문제로만 표시). 사진 PDF는 규칙 방식으로 읽지 못한다.
- 사진 경로: 띠 실패는 포괄 메시지만 남는다. 세 자리 OCR 숫자는 "AI가 읽지 않았다"로 보고하지 않는다. OCR 토큰이 없는 두 행은 겹친 띠의 반복으로 합칠 수 있다. 계정명을 확인하지 못한 칸은 메모만 있고 "확인 필요"가 아니다.
- 개발 측정과 개발 정답은 개발에 쓴 문서라 평가가 아니다. 정답 생성기와 제품은 같은 글자 층을 읽는다.
