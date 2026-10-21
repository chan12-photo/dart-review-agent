# D5 계약·도구 Codex 3차 검토에 대한 응답 (2026-10-21)

- 대상: `docs/reviews/D5_contract_recheck2_codex_result.ko.md` (기준 `cbe7cbd`)
- 검토 실행: Claude가 `codex exec`로 돌렸다(사용자 허락). 모델은 `gpt-5.6-sol`, 추론 xhigh다.
- **결론:** 4건을 모두 받아들였다.
  - 고친 도구는 커밋 `be10b549c862f95826c0f4cd4fdfd57442a77f4a`에 있다.
  - 계약은 초안 4판이다. 이 응답과 계약 4판, 3차 결과는 그 다음 커밋에 넣었다.
  - D4 공식 결과는 바꾸지 않았다.

## 고정 전에 고칠 것

### 1. [치명] F와 R 사이에 N을 바꿀 수 있음 → F를 원격 태그 `d5-frozen`으로 고정

- **절차:** ④에서 고정 기록만 담은 커밋 F를 만들고, 주석 태그 `d5-frozen`을 달아 `origin`에 push한다. 그 전에는 후보 PDF를 열지 않는다(계약 1·2절). 태그 이름은 `PROFILES["d5"]["frozen_tag"]`에 있다.
- **등록 (`register --profile d5 --remote origin`):**
  - 로컬 `d5-frozen`이 있어야 한다.
  - `origin`의 `d5-frozen`이 같은 커밋 F를 가리켜야 한다.
  - HEAD의 `eval/freeze_d5.json`이 F의 것과 같은 Git 객체여야 한다.
  - 하나라도 아니면 등록하지 않는다. 등록 기록에는 `frozen_commit`과 `freeze_object`를 적는다.
  - `--remote` 없이는 CLI가 거부한다.
- **점검 (`check --profile d5`):**
  - 등록 기록의 F·객체가 로컬 `d5-frozen`과 F의 고정 기록 객체와 같아야 하고, HEAD의 고정 기록도 그 객체여야 한다.
  - F는 HEAD의 조상이어야 한다.
  - `--remote`가 있으면 원격 `d5-frozen`도 F를 가리켜야 한다.
- **시험 (`ProfileTests`):**
  - Codex 반례(F에서 N = 2로 정한 뒤 N과 목록을 1로 함께 줄임)는 등록에서 "not the record frozen at F"로 거부된다(`test_n_changed_between_f_and_r_is_refused`).
  - 바뀐 기록으로 등록 기록을 손으로 만들어도 점검이 실패한다(같은 시험).
  - 원격 태그를 지운 경우와 로컬 태그를 지운 경우에도 등록과 점검이 모두 실패한다(`test_f_must_be_tagged_and_pushed`).
- **남는 한계:** 원격 태그 자체를 지우고 다시 다는 것은 이 도구로 막을 수 없다. 원격 저장소의 권한 문제이며, D4의 `d4-registered`와 같은 수준의 신뢰다.

### 2. [중요] 등록 기록 자체가 링크 → 거부

- **CLI:** `--profile d5`이면 고정·등록 기록의 자리가 링크 없이 도달하는 곳이어야 한다(`inside`와 `is_symlink`). 아니면 기록을 만들거나 읽기 전에 멈춘다.
- **점검:** 고정·등록 기록이 HEAD에서 일반 파일(모드 100644·100755)이고 링크 없이 도달하는지 본다(`regular_at_head`).
- **시험:**
  - 등록 기록을 저장소 밖으로 가는 링크로 바꿔 커밋하면 점검이 실패한다(`test_a_registration_record_linked_out_of_the_repository_fails_the_check`).
  - CLI는 이 작업 폴더에서 직접 확인했다. 임시로 `eval/register_d5.json` 링크를 만들자 `register`와 `check`가 모두 "reached through a link"로 멈췄고, 링크 대상은 바뀌지 않았다. 확인 뒤 링크는 지웠다.

## 계약에 적을 것

### 3. [사소] D4 재집계 JSON의 새 필드 → D4에서는 쓰지 않음

- `expected_documents`는 D5 프로필 집계에만 쓴다.
- D4 저장 보고서를 `be10b54`의 도구로 다시 집계했다. 최상위 키가 `official.final2.json`과 같고, 네 판정과 수치도 같다.
- 계약 4절에 D4 기록 형식이 그대로라는 문장과 이 예외의 처리를 적었다.

### 4. [사소] ⑧ 실행기 명령의 필수 인자 → 전체 명령

- 계약 2절에 `--pdf-dir`, `--scan-dir`, `--out`, `--documents`, `--preflight`를 모두 담은 전체 명령을 적었다.
- 폴더 이름만 절차서에서 정한다.

## 다시 확인

- **시험:** 작업 폴더에서 전체 574개 중 489개가 통과했다. 개발 캐시가 필요한 85개는 건너뛰었다.
  - 새 시험 3개: F 사이 N 변경, F 태그, 링크된 등록 기록
  - 고친 시험: 프로필 시험의 등록 호출(원격 인자)
- **D4 재집계 (`be10b54`):** 규칙 텍스트 S1 0·L1 0·S2 1, 규칙 스캔 3·2·6652, AI 텍스트 11·4·0, AI 스캔 27·0·5559. 모두 미충족으로 그대로다.

## 다음

- 같은 범위의 짧은 4차 확인 검토를 Claude가 `codex exec`로 돌린다.
- 그 뒤 `d5-tools`를 `main`에 합친다.
