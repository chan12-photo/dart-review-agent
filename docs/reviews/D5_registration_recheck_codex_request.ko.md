# Codex 확인 요청: D5 평가 등록 전 검토의 수정 (2026-10-21)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_registration_recheck_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. **제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다.** 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_registration_recheck_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 임시 파일은 `/tmp` 아래에만 만든다. `~/Desktop/D5/`는 읽기만 한다. 칭찬은 필요 없다.

대상: `git diff 4069799..HEAD`. 앞 결과는 `docs/reviews/D5_registration_codex_result.ko.md`, 응답은 `docs/reviews/D5_registration_codex_response.ko.md`다.

기준: **앞 검토의 5건이 닫혔는가, 수정이 새 문제를 만들었는가.** 짧은 확인이다. 범위를 넓히지 말고 앞의 반례(붙은 두 금액, 1·100·200pt의 세 줄)를 다시 돌려 줘.
- 145개 결정과 정답 칸이 그대로인지 본다.
- 바뀐 메모 7개가 맞는지 본다.
- 대체 경로가 두 자리 밖에서 멈추는지 본다.
- 계약·메모의 기록 문구가 맞는지 본다.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"등록 전에 반드시 고칠 것"과 "기록할 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 앞 검토의 "이미 알고 있는 것" 전부
- 매핑표는 사용자 확인 전 초안이다
