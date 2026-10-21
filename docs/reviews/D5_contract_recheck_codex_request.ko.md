# Codex 재검토 요청: D5 계약 초안 2판과 1차 검토 수정 (2026-10-20)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_contract_recheck_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. 제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_contract_recheck_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다.

읽어도 되는 것: `~/Desktop/D4/`(D4 PDF, 수정 금지), `~/Documents/ChatGPT/dart-review-agent/cache/d4/`(OpenDART 캐시, 수정 금지), `eval/d4_eval/results/2026-10-20/`.

대상: `git diff 1547a2c..HEAD`. 1차 검토 결과는 `docs/reviews/D5_contract_codex_result.ko.md`, 응답은 `docs/reviews/D5_contract_codex_response.ko.md`, 계약은 `docs/EVAL_CONTRACT_D5.ko.md`(초안 2판)다.

기준: **1차 지적 7건이 닫혔는가, 수정이 새 거짓 충족 경로나 D4 기본 동작의 변화를 만들었는가.**

1. **문서 목록 검사(`eval/d4_eval/document_list.py`):**
   - 1차의 반례(일부·중복 목록으로 `met`)가 닫혔는가.
   - 실행기·위치 검사·집계 중 검사를 건너뛰는 경로가 있는가. `repo_paths=False`인 두 곳(집계·위치 검사)이 허점이 되는가.
   - D4 자기 목록일 때만 10으로 보는 판단(`is_d4_list`)이 우회되는가.
2. **고정·사전 점검(`eval/d4_preflight.py`의 `--tool-paths`, `--tag`):** D4 기본 동작이 그대로인가. D5 경로로 쓸 때 고정 기록·등록·점검이 서로 맞는가.
3. **점 날짜(`DOTTED_PERIOD`, `dated()`):**
   - 기간 줄 전체만 받는가.
   - 실제 감사보고서에 나올 만한 기간 줄 변형을 놓쳐 재무제표를 못 찾는 경우가 있는가. 그런 경우 계약상 `statement_not_found`로 사람에게 넘어가는가.
   - D4 정답 10개를 다시 만든 결과가 응답의 주장과 같은가(9개 바이트 동일, DSR 211/212).
4. **계약 2판:** 파일 표와 명령이 코드와 맞는가. 제품 P를 닫힌 목록으로 둔 것과 후보 기록 복사 규칙이 1차 5·6번을 닫는가. 남은 공백이 있는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"고정 전에 반드시 고칠 것"과 "계약에 적을 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 1차 검토의 "이미 알고 있는 것"과 D4 검토들의 것 전부
- D5를 할지는 사용자가 아직 정하지 않았다(계약 9절)
