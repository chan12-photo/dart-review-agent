# Codex 확인 요청: D5 등록 전 재확인의 수정 한 건 (2026-10-21)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_registration_recheck2_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. 제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_registration_recheck2_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 임시 파일은 `/tmp` 아래에만 만든다. `~/Desktop/D5/`는 읽기만 한다. 칭찬은 필요 없다.

대상: `git diff a2309ad..HEAD`의 `eval/d5_eval/draft_mappings.py`(`_printed_on`). 재확인 결과는 `docs/reviews/D5_registration_recheck_codex_result.ko.md`, 응답은 `docs/reviews/D5_registration_codex_response.ko.md`의 "재확인" 절이다.

기준: **`△` 지적이 닫혔는가, 이 수정이 새 문제를 만들었는가.** 아주 짧은 확인이다.
- 정답 생성기의 `GROUPED`·`SMALL`이 금액으로 읽는 표기와 `_printed_on`이 찾는 것이 일치하는지 본다.
- 145개 결정과 메모가 그대로인지 본다.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

없으면 "등록 전에 고칠 것 없음"이라고 분명히 적어 줘.
