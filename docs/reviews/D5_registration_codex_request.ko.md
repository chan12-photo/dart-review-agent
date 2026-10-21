# Codex 검토 요청: D5 평가 등록 전 (⑦ 전, 2026-10-21)

- 실행: Claude가 `codex exec`로 돌린다(사용자 허락). 결과는 `docs/reviews/D5_registration_codex_result.ko.md`에 저장한다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않는다. **제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행)을 어떤 PDF에도 돌리지 않는다.** 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D5_registration_codex_result.ko.md` 한 파일에만 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 임시 파일은 `/tmp` 아래에만 만든다. 칭찬은 필요 없다.

읽어도 되는 것:
- `~/Desktop/D5/`(D5 평가 PDF 10개와 `scans/`의 합성 스캔 30개, 수정 금지)
- `cache/d4/`(OpenDART 캐시, 수정 금지)
- 저장소 전체

정답 생성기(`eval/d4_gold.py`의 `build`·`lines_of`), 스캔 대응표, 위치 검사의 `build`, 실행기의 `--dry-run`처럼 제품을 부르지 않는 도구는 써도 된다.

대상: ④ 고정 뒤의 모든 것, `git diff d5-frozen..HEAD`. 계약은 `docs/EVAL_CONTRACT_D5.ko.md` 6판(특히 11절 개정), 절차서는 `docs/D5_RUN_PROCEDURE.ko.md`, 확인 안내는 `eval/d5_eval/REVIEW_GUIDE.ko.md`다.

기준: **등록(⑦)해도 되는가.** 거짓 충족(표시 없이 틀린 것이 기준을 통과하는 것)이나, 정답·자리·목록이 인쇄와 어긋나 판정이 틀어지는 경로가 있는지 본다.

1. **후보 판정 (`eval/d5_candidates/`, `eval/d5_excluded.json`):**
   - 20~30번 복사 기록이 원본(`eval/d4_candidates/`)과 맞는가.
   - 31~40번 조회와 첨부 이름 기록, `select`의 판정, 받기·글자 층 검사, 10곳에서 멈춘 것이 계약 5절과 D4 3.2를 따르는가.
2. **정답과 매핑 초안 (`eval/d5_eval/gold/`, `draft_mappings.py`):**
   - 세 근거 규칙(keep: 한 줄에 계정명·금액과 열, ignore: 인쇄 없음 또는 이미 정답 칸인 줄)이 틀린 결정을 낼 수 있는가.
   - 명시 결정 4개가 맞는가: 차바이오텍 n1/n13/n14, 한독 n1, 꿈비 n12.
   - 정답 생성기가 빠뜨린 인쇄 행이나 잘못 만든 칸(한독의 열 머리글 같은)이 더 있는가. 몇 문서를 PDF와 직접 대조해 줘.
3. **위치 검사 자리 (`duplicate_places.json`, `build_places.py`):**
   - 감긴 계정명 대체 경로가 고정 도구와 같은 규칙인가.
   - 대체 경로가 틀린 행을 고를 수 있는가.
   - 나머지가 고정 도구 결과와 같은가.
   - 실행 뒤 `position_check.check`와 공식 집계가 이 파일을 문제없이 쓰는가.
4. **문서 목록과 스캔 (`documents.json`, `scans/`):**
   - 해시가 받은 PDF·스캔과 맞는가.
   - 고정 도구(`registered_count`, `check_document_list`, 실행기 `--dry-run`)가 받는가.
5. **절차서와 계약 6판:**
   - ⑦~⑨ 명령이 고정 도구(d5 프로필의 `register`·`check`, 실행기, 집계)와 맞는가.
   - ⑦ 5번의 등록 파일 목록이 프로필의 요구(목록·자리·정답·매핑표·대응표 전부)를 채우는가.
   - 11절 개정이 계약의 다른 절과 충돌하는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과)
- 가장 작은 수정

"등록 전에 반드시 고칠 것"과 "기록할 것"을 나누고, 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것

- 매핑표는 아직 초안이다(사용자 확인 전). 확인 뒤 `status`만 바뀌고, 결정이 바뀌면 자리를 다시 만든다.
- 고정 도구 T와 제품 P는 ④ 뒤에 바꾸지 않는다. 고칠 것이 도구라면 계약 개정과 다시 고정하는 문제가 되니, 그 경우 데이터·절차 쪽의 가장 작은 처리도 함께 적어 줘.
- D5 계약 검토 1~5차와 D4 검토들의 "이미 알고 있는 것" 전부.
