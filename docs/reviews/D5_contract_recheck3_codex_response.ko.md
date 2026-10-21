# D5 계약·도구 Codex 4차 확인에 대한 응답 (2026-10-21)

- 대상: `docs/reviews/D5_contract_recheck3_codex_result.ko.md` (기준 `9b53f69`)
- 검토 실행: Claude가 `codex exec`로 돌렸다(사용자 허락). 모델은 `gpt-5.6-sol`, 추론 xhigh다.
- **결론:**
  - 3차의 네 반례가 닫혔다는 확인을 받았다. F의 N 변경, 기록 링크(등록·고정 둘 다), D4 형식, ④·⑦·⑧ 명령이다.
  - 새로 찾은 **중요 1건**을 받아들여 고쳤다. 고친 도구는 커밋 `e71ec90dff176fc4427ac2c6d4a0633b2149984f`, 계약은 초안 5판이다.

## 1. [중요] F 옆 가지에서 등록하고 F를 병합해 R을 만들면 통과

- **등록 (`register_record`, D5):** F가 등록 시점 HEAD의 조상이 아니면 등록하지 않는다.
- **점검 (`check`, D5):** Codex의 최소 수정(조상 관계와 `based_on` 객체 대조)보다 한 단계 더 좁혔다. R은 등록 커밋 그 자체여야 한다.
  - R의 부모는 등록 기록의 `based_on` 하나뿐이다. 병합 커밋은 실패한다.
  - `based_on`과 R 사이에 바뀐 파일은 등록 기록 하나뿐이다.
  - F는 `based_on`의 조상이다.
  - 등록 파일 각각이 `based_on`에서도 기록된 객체다.
  - 이렇게 하면 손으로 `based_on`만 바꾼 기록도 부모 관계에서 걸린다.
- **절차:** D4와 같다. 등록 명령 → 등록 기록만 커밋해 R → 태그. 정상 절차는 이 조건을 그대로 만족한다(`ProfileTests`의 정상 R이 모든 점검을 통과).
- **시험:**
  - `test_a_registration_beside_f_merged_in_afterwards_is_refused`: Codex 반례 그대로다. F와 같은 고정 기록 객체를 가진 비조상 가지 SIDE를 만든다.
    - SIDE에서의 등록은 "is not an ancestor of HEAD"로 거부된다.
    - `based_on = SIDE`인 기록으로 `merge(SIDE, F)`를 R로 만들면 점검의 두 항목이 실패한다. "R's only parent…"와 "F … is an ancestor of the registered commit"이다.
  - `test_r_is_exactly_the_registration_commit`: 등록 뒤 등록 파일을 바꾼 커밋은 점검이 실패한다.
- **계약:** 2절 ⑦에 "등록 시점 HEAD는 F의 자손", "R은 등록 기록만 더한 단일 부모 커밋"을 적었다. ⑧ 점검 목록에 새 항목들을 적었다.

## 다시 확인

- 작업 폴더에서 전체 576개 중 491개가 통과했다. 개발 캐시가 필요한 85개는 건너뛰었다.
- D4의 점검·집계 경로는 바꾸지 않았다. 새 항목은 D5 프로필에서만 돈다. D4 재집계는 3차 응답과 같다.

## 다음

- 같은 범위의 짧은 5차 확인을 Claude가 `codex exec`로 돌린다. 이번 수정 한 건만 본다.
- 그 뒤 `d5-tools`를 `main`에 합친다.
