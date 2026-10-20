# Codex 4차 확인 요청: D5 3차 검토 수정과 계약 초안 4판 (2026-10-21)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_contract_recheck3_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. 제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_contract_recheck3_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 임시 파일과 임시 Git 저장소는 `/tmp` 아래에만 만든다. 칭찬은 필요 없다.

대상: `git diff cbe7cbd..HEAD`. 3차 결과는 `docs/reviews/D5_contract_recheck2_codex_result.ko.md`, 응답은 `docs/reviews/D5_contract_recheck2_codex_response.ko.md`, 계약은 `docs/EVAL_CONTRACT_D5.ko.md`(초안 4판)다.

기준: **3차 지적 4건이 닫혔는가, 수정이 새 거짓 충족 경로나 D4 기본 동작의 변화를 만들었는가.** 짧은 확인 검토다. 새 범위를 넓히지 말고, 3차의 반례를 그대로 다시 돌려 확인해 줘.

1. **F 고정 (`d5-frozen`, `register_record(..., remote)`, `check`의 F 항목):**
   - 3차 반례(F에서 N = 10, F와 R 사이에 N과 목록을 1로 줄임)가 등록과 점검에서 모두 거부되는가.
   - 태그를 다른 커밋에 다시 달거나 F의 조상·자손 관계를 바꿔 통과하는 경로가 있는가.
2. **기록 링크 (CLI의 자리 검사, `regular_at_head`):** 3차 반례(등록 기록이 저장소 밖으로 가는 링크)가 닫혔는가. 고정 기록 쪽은 어떤가.
3. **D4 형식:** D4 재집계 JSON의 최상위 키가 `official.final2.json`과 같은가. D4 기존 고정·등록 기록과 점검 로그가 그대로 받아들여지는가.
4. **계약 4판:** 2절의 ④·⑦·⑧ 명령과 F 절차가 코드와 맞는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"고정 전에 반드시 고칠 것"과 "계약에 적을 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 1~3차의 "이미 알고 있는 것"과 D4 검토들의 것 전부
- 원격 태그 자체를 지우고 다시 다는 것은 원격 저장소 권한의 문제로, 도구 밖이다(응답 1번)
- D5를 할지는 사용자가 아직 정하지 않았다(계약 9절)
