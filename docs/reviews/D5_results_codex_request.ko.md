# Codex 검토 요청: D5 평가 결과 (공개 전, 2026-10-21)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_results_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. **제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다.** 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_results_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 임시 파일은 `/tmp` 아래에만 만든다. `~/Desktop/D5/`와 `~/D5_official/`은 읽기만 한다. 칭찬은 필요 없다.

대상:
- `eval/d5_eval/results/2026-10-21/`: `REPORT.ko.md`, `official.final.json`, `judgments/run2/`, `run2/`, `run1/`, `MANIFEST.json`
- 계약 `docs/EVAL_CONTRACT_D5.ko.md` 6판, 절차서 `docs/D5_RUN_PROCEDURE.ko.md`, 등록 R(태그 `d5-registered`)

기준: **공개해도 되는가.** 결과가 계약·절차대로 나왔는지, 보고서가 결과를 과장하거나 줄이지 않는지 본다.

1. **실행:** run2가 R에서 절차대로 돌았는가(사전 점검 로그, `run.json`, `run_log.jsonl`). run1을 공식에서 뺀 처리와 run2로 다시 돌린 것이 절차서 ⑧ 6번과 맞는가.
2. **판정 15개:** 위치 13곳 `ok`, 정답 밖 칸 2개 `wrong`이 계약 6절과 D4 4.5·4.6에 맞는가. PDF와 제품 보고서로 직접 확인해 줘.
3. **공식 집계:** 고정 도구로 다시 집계해 `official.final.json`과 같은가(저장소의 결과 폴더로; 커밋하지 않은 보고서 2개는 `~/D5_official/run2`에서 읽는다).
4. **보고서:** 수치·원인 설명(2절)·D4 비교(3절)·규칙 방식 해석(4절)·한계(7절)가 기록과 맞는가. 빠진 한계가 있는가.
5. **보관:** `MANIFEST.json`의 해시, 경로를 `~`로 바꾼 파일, 커밋하지 않은 2개의 처리가 맞는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"공개 전에 반드시 고칠 것"과 "기록할 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 등록 전 검토 3회와 D5 계약 검토 5회, D4 검토들의 "이미 알고 있는 것" 전부
- 고정 도구와 제품은 바꾸지 않는다. 판정 결과에 따라 판정이나 보고서를 고칠 수는 있다(D4 결과 검토처럼, 사용자 재결정).
