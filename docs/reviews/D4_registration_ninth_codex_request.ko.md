# Codex 9차 검토 요청: 8차 수정만 (⑦ 전, 선택, 2026-10-20)

- 사용 방법: 이 저장소 폴더에서 Codex를 열고 아래 요청문을 붙여 넣는다. 결과는 `docs/reviews/D4_registration_ninth_codex_result.ko.md`로 저장한다.
- 선택인 이유:
  - 8차 수정은 입력 검사 두 곳이고, Codex의 반례가 그대로 시험이 됐다.
  - 그 시험은 고치기 전 코드에서 실패했다.
  - 정직한 실행의 기록이 막히지 않는 것도 실제 실행기 출력으로 시험했다.

  등록 전에 한 번 더 확인받고 싶으면 쓴다.

---

## 요청문

`AGENTS.md`를 따른다. 인증키, OpenDART API, Ollama, 네트워크는 쓰지 않고, 제품(`python -m dart_review extract`, `eval/d4_score.py --pdf`, `eval/d4_eval/run_d4.py`의 실제 실행)을 평가 문서에 **돌리지 않는다**. 추적 파일은 수정하지 말고, 결과는 `docs/reviews/D4_registration_ninth_codex_result.ko.md`에 저장해 줘. 결과에 로컬 홈 디렉터리의 절대 경로는 쓰지 말고 `~/`로 적어 줘. 칭찬은 필요 없다.

대상은 `f92a91a..HEAD`다. 8차 결과와 응답은 `docs/reviews/D4_registration_eighth_codex_{result,response}.ko.md`에 있다.

기준은 같다. **등록한 대로 정직하게 실행하면 틀린 공식 결과(특히 거짓 `met`)가 나올 경로가 남았는가.** 계약 1.3의 신뢰 경계 밖은 범위 밖이다. 이번에는 반대 방향도 봐 줘. **정직하게 실행한 기록이 관문에 막혀 공식 판정이 불가능해지는 경로가 있는가**(관문이 너무 엄격한가).

1. `eval/d4_eval/official_d4.py run_gate`: 실행 기록 전체의 일치 검사가 8차 1번을 닫는가. 실제 `run_d4.py`가 쓰는 `run.json`·`run_log.jsonl`(모든 호출 성공, 일부 실패, 한 방식만 다시 돌림)을 막지 않는가. `tests/test_d4_run.py`의 두 통합 시험이 이것을 충분히 보이는가.
2. 판정 파일 모양 검사(`official_d4.py call`, `position_check.py check`)가 8차 2번을 닫는가. 정상 판정 파일을 거부하는 경우가 있는가.
3. 실행기의 `--readers` 순서 검사, 집계의 방식 중복 제거, 깨진 보고서 거부, `judgment_files_not_read`가 다른 동작을 바꾸지 않는가.
4. 계약 7판 4.6·5절·10절과 절차서 ⑨의 판정 폴더(`judgments/run1/`)가 코드와 같은가.
5. 고정 경로(`git diff 49c182b HEAD -- dart_review pyproject.toml eval/d4_{gold,score,candidates,preflight,scan}.py`)가 비어 있고, `position_check.py verify --pdf-dir ~/Desktop/D4`가 66곳 같음을 내는가.

각 발견에 다음을 적어 줘.
- 심각도
- 위치
- 근거(명령과 결과, 합성 반례)
- 가장 작은 수정

"등록 전에 반드시 고칠 것"과 "보고서에 적을 것"을 나눠 주고, 등록 전에 고칠 것이 없으면 그렇다고 분명히 적어 줘.

## 이미 알고 있는 것 (다시 적지 않아도 됨)

- 7차, 7차 재검토, 8차의 "이미 알고 있는 것" 전부
- 실행 기록이 조금이라도 어긋나면 그 폴더 전체가 공식이 될 수 없다(의도한 엄격함. 새 폴더에서 다시 돌린다)
