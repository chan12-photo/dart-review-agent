# Codex 3차 검토 요청: D5 재검토 수정과 계약 초안 3판 (2026-10-20)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_contract_recheck2_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. 제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_contract_recheck2_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다.

읽어도 되는 것: `~/Desktop/D4/`(D4 PDF, 수정 금지), `~/Documents/ChatGPT/dart-review-agent/cache/d4/`(OpenDART 캐시, 수정 금지), `eval/d4_eval/results/2026-10-20/`. 저장소 밖에 무언가를 만들어야 하면 `/tmp` 아래 임시 폴더만 쓴다.

대상: `git diff 4bf93e1..HEAD`. 재검토 결과는 `docs/reviews/D5_contract_recheck_codex_result.ko.md`, 응답은 `docs/reviews/D5_contract_recheck_codex_response.ko.md`, 계약은 `docs/EVAL_CONTRACT_D5.ko.md`(초안 3판)다.

기준: **재검토 지적 4건이 닫혔는가, 수정이 새 거짓 충족 경로나 D4 기본 동작의 변화를 만들었는가.**

1. **목록 밖의 N (`document_list.registered_count`, `frozen_count`, `check_document_list`):**
   - 재검토 반례(10개로 정했는데 스스로 1개·9개라고 말하는 목록)가 실행기·위치 검사·집계·등록에서 모두 닫혔는가.
   - N을 담은 고정 기록 자체를 ④ 뒤에 바꾸는 경로가 있는가. 등록 기록·태그·점검이 그 변경을 잡는가. R 밖에서 도는 집계(⑨)는 어떤가.
2. **링크 (`document_list.inside`, `is_d4_list`, `register_record`):** 저장소 밖 파일이나 D4 목록으로 가는 링크가 아직 통과하는 경로가 있는가(파일 링크, 폴더 링크, 대소문자·`..`·절대 경로 같은 글자 변형).
3. **D5 프로필 (`PROFILES["d5"]`, `freeze/register/check --profile`, 실행기의 로그 프로필 확인):**
   - 도구 9개·P·태그·N이 고정·등록·점검에 서로 묶였는가.
   - D4/D5 태그나 기록을 섞어 통과하는 경로가 있는가.
   - D4 기본 동작과 기록 형식이 그대로인가. D4의 기존 고정·등록 기록, 실행 로그, 공식 결과 재집계로 확인해 줘.
4. **계약 3판:** 2절의 ④·⑦·⑧ 명령이 코드와 맞는가. 4절의 해시와 점 날짜 변형 문구가 맞는가. 남은 공백이 있는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"고정 전에 반드시 고칠 것"과 "계약에 적을 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 1차·재검토의 "이미 알고 있는 것"과 D4 검토들의 것 전부
- 받지 않는 점 날짜 변형(같은 줄의 단위, 한 줄의 두 날짜, 물결표 범위)은 `statement_not_found`로 사람에게 넘어간다(재검토 확인, 계약 4절)
- 절차서 `docs/D5_RUN_PROCEDURE.ko.md`와 ⑨의 정확한 명령은 ⑥ 전에 쓰고 등록 전 Codex 검토를 받는다
- D5를 할지는 사용자가 아직 정하지 않았다(계약 9절)
