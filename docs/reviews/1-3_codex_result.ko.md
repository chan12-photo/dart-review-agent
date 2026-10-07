# 재무 규칙 1-2·개발용 질문/정답 1-3 독립 검토

- 작성: Codex, 2026-10-07 (Asia/Seoul)
- 대상 커밋: `b1c5f27f83f90758abf3579ac43a030bf86ad26a`
- 검토 시점: 1-3 완료, 1-4 평가 실행기 구현 전
- 저장소: `dart-review-agent`. 시작 시 `git status --short` 출력 없음.
- 범위: 읽기와 오프라인 실행. 제품·규칙·질문·정답·테스트의 추적 파일 32개를 변경하지 않았다. 이 검토 보고서만 신규 파일로 저장했다.
- 실제 인증키 파일은 열지 않았고 OpenDART·LLM 호출은 하지 않았다. 기존 테스트의 인증키 관련 검증은 임시 가짜 키를 사용하는 테스트다. 봉인된 회사의 응답과 회사 목록 ZIP은 열지 않았다.

## 결론

**저장된 12개 정답에서 금액·변화량·변화율·근거 칸·기간 라벨의 불일치는 발견하지 못했다. 다만 이를 규칙과 정답 검증의 완전성으로 해석하면 안 된다.** 숫자가 있는 9개 질문 중 변화 계산은 8개이며, 나머지 1개는 연결·별도 병렬 표시다. dev10·11·12는 거절·데이터 없음·되묻기여서 계산할 금액이 없다. 상태는 캐시만의 객관적 속성이 아니라 제품 정책을 포함하므로 아래 조건부 판단을 함께 적용한다.

치명으로 분류한 발견은 없다. 우선 검토할 중요 사항은 다음 5개다.

1. 필요한 재작성 확인 자료가 없어지면, 경고해야 하는 사례가 `비교 가능`으로 바뀐다. 013/계정 누락에서는 점검 미완료 메모도 없다.
2. 잘못 지정한 `restated_pair`가 정답 생성·대조를 통과한다.
3. 합계 행 필터를 제거해도 기존 테스트 68개가 모두 통과한다.
4. 이름 대체가 의미가 다른 표준 ID까지 받아들이며, 해당 충돌을 일반적인 비교로 진행할 수 있다.
5. 양쪽 통화가 모두 미확인이면 통화 검증을 통과하고 계산한다.

1-4 구현 전에 적어도 1~3번과 상태·정답 정책을 정리하는 것을 권한다. 이번 검토에서는 수정을 수행하지 않았다. 각 항목에 실제 캐시 재현인지 합성 경계 사례인지 표시했다.

## A. 독립 재계산

부록 A의 새 코드는 `dart_review`와 `eval/build_gold.py`를 import하지 않는다. 원본 `.meta.json`에서 요청을 식별하고 `.body`의 SHA-256을 검증한 뒤, 질문 문장에 맞춰 별도로 지정한 행과 칸을 읽었다. 생산 코드의 기간 함수도 사용하지 않았다. 변화율은 생산 코드의 Decimal 계산을 복사하지 않고 정수 몫·나머지로 소수 둘째 자리의 HALF_UP을 구현했다. 정답 JSON은 계산을 끝낸 다음 대조에만 사용했다.

검사한 재무 캐시: 개발용 72건과 삼성전자 2014 사업보고서 013 응답 1건, 총 73건. 본문 SHA-256은 모두 메타데이터와 일치했다.

단위는 원, 변화율은 %다. `—`는 계산 대상이 아님 또는 정책상 생략이다.

| ID | 당기/연결 | 기준/별도 | 변화량 | 변화율 | 독립 판단과 저장 상태 대조 |
|---|---:|---:|---:|---:|---|
| dev01 | 333,605,938,000,000 | 300,870,903,000,000 | 32,735,035,000,000 | 10.88 | 비교 가능 |
| dev02 | 523,659,586,000,000 | 491,307,317,000,000 | 32,352,269,000,000 | 6.58 | 비교 가능 |
| dev03 | 56,515,496,000,000 | 50,960,350,000,000 | 5,555,146,000,000 | 10.90 | 비교 가능 |
| dev04 | 693,299,607,299 | 295,611,507,111 | 397,688,100,188 | 134.53 | 비교 가능 |
| dev05 | 333,605,938,000,000 | 238,043,009,000,000 | — | — | 비교 불가/나란히 표시 — 단순 차액 허용은 별도 정책 판단 |
| dev06 | 2,160,931,354,165 | 2,042,475,603,587 | 118,455,750,578 | 5.80 | 비교 가능 |
| dev07 | 732,036,535,379 | 495,277,757,353 | 236,758,778,026 | 47.80 | 비교 가능 |
| dev08 | 3,275,436,431,552 | 2,431,791,719,869 | 843,644,711,683 | 34.69 | 확인 필요 — 간접 증거에 따른 조건부 경고 |
| dev09 | 517,959,587,282 | -161,870,567,171 | 679,830,154,453 | — | 비교 가능 / 흑자 전환 |
| dev10 | — | — | — | — | 비교 불가 — 직접 제공되지 않는 7~9월 CF |
| dev11 | — | — | — | — | 데이터 없음 — 요청한 2014 보고서 응답 013 |
| dev12 | — | — | — | — | 되묻기 — 영업이익/당기순이익 미선택 |

대조 결과: 계산·선택한 칸·접수번호·통화·기간 라벨 불일치 0건. dev11은 해당 요청의 013을 확인한 것이며, 다른 연도의 비교 칸까지 포함한 모든 경로에서 2013~2014년 수치를 절대로 구할 수 없다고 증명한 것은 아니다. dev12는 원본 수치 계산 대신 질문 해석을 검토했다. dev05·dev08의 상태를 회계적으로 유일한 정답이라고 주장하지 않는다.

## B. 발견 사항

### R1 — 중요: 점검 불완전이 비교 가능으로 승격됨

- 위치: `dart_review/review.py:48`, `review.py:59`, `review.py:63`, `review.py:68`, `review.py:70`; `tests/test_rules.py:269`.
- 유형: **실제 dev08 캐시 + 읽기 결과만 메모리에서 제한한 재현**. 원본 캐시를 삭제·변경하지 않았다.
- 근거: 정상 조회에서는 셀트리온 별도 부채가 2,431,791,719,869 → 3,275,436,431,552, 차이 843,644,711,683, 34.69%이며 `확인 필요`다. 경고 근거는 2023년 말 부채 2,230,608,519,706 → 2,256,044,979,595의 보고서 간 차이다.
- 실행: 부록 B `probes.py`의 `bridge_*`. 2024 사업보고서만 `NotCached`로 보이게 하면 **동일한 숫자가 `비교 가능`**으로 바뀐다. 메모는 남는다. 그 응답을 013 또는 계정 없는 000 응답으로 보이게 하면 **`비교 가능`이며 점검 미완료 메모도 없다**.
- 문제: 실제 기준이 같아진 것이 아니라 반증을 찾을 자료가 사라진 것이다. `비교 가능`을 검증 완료로 소비하는 평가기·출력에서는 잘못된 확신을 준다. 기존 테스트는 미완료+`비교 가능`을 기대하므로 이 정책을 고정한다.
- 제안: 당기·기준 금액의 존재와 재작성 점검 완료 여부를 구별한다. 필요한 연결 보고서가 없거나 대상 계정/필요 칸이 없거나 모호하면 `확인 필요(재작성 점검 미완료)`와 계산 가능한 숫자를 반환하는 보수적 정책이 적절하다. 다른 정책을 택한다면 적어도 미완료를 명시적으로 평가·출력하고, 013/계정 누락을 조용히 무시하지 않아야 한다. 겹치는 기간이 원래 없는 비교도 동일한 검증 범위 설명이 필요하다.

### R2 — 중요: 틀린 재작성 근거를 지정해도 정답 대조가 통과함

- 위치: `eval/build_gold.py:146`, `build_gold.py:154`, `build_gold.py:160`, `build_gold.py:183`, `build_gold.py:189`; `eval/dev_questions.json:165`.
- 유형: **실제 캐시, 질문 복사본의 근거만 메모리에서 변경**.
- 근거: dev08의 `restated_pair`를 2025-09-30 당기 3,275,436,431,552와 2024-09-30 당기 2,431,791,719,869로 교체했다. 이 둘은 다른 기간의 부채이며 동일 기간의 재작성 쌍이 아니다.
- 실행 결과: 부록 B `wrong_restated_pair.cross_check_problems == []`. 생성기는 두 금액이 다르다는 것만 검사한다. 대조기는 제품 코드가 찾아낸 별도의 정상 재작성 사유에 `재작성`, `2023-12-31`이 들어 있는지만 확인하므로, **정답 파일에 들어간 틀린 근거 자체는 놓친다**.
- 제안: 근거 쌍의 회사·연결/별도·계정 의미·대상 기간·통화 동일성, 보고서 식별, 값 차이를 독립 검증한다. 제품 결과의 재작성 근거도 정확한 두 접수번호·칸·금액과 대응시킨다. 이유 키워드만으로 근거 정합성을 대체하지 않는다.
- 추가 독립성 한계: `build_gold.py:34`, `:51`, `:135`는 기간과 라벨을 생산 코드와 공유한다. 기간 값 라벨만 `WRONG FLOW PERIOD`로 바꾸면 전체 `build()` 대조는 문제 0건으로 통과한다(부록 B `shared_period_label`). 저장된 gold와의 `--check`는 기존 파일과 달라져 탐지할 수 있지만, **잘못된 라벨을 재생성하는 단계에서는 독립 검증이 없다**. “금액 계산은 독립, 기간 표현 일부는 공유”라고 문서를 정확히 쓰고 날짜·기간 길이의 기대값을 독립 검증해야 한다. 현재 숫자가 틀렸다는 주장은 아니다.

### R3 — 중요: 합계 행만 선택하는 규칙의 테스트가 다른 필터에 가려짐

- 위치: `tests/test_rules.py:129`, `dart_review/accounts.py:77`, `accounts.py:83`, `scripts/check_trap_tests.py:76`.
- 유형: **메모리에서 함수 교체 + 전체 기존 테스트 실행**.
- 근거: `test_breakdown_rows_and_other_statements_are_ignored`의 분해 행은 SCE에 있다. 순이익 대상 재무제표는 IS/CIS이므로 `account_detail`을 검사하지 않아도 재무제표 필터가 먼저 버린다. 이 테스트는 재무제표 제외는 검증하지만 합계 행 필터는 독립적으로 검증하지 못한다.
- 실행 결과: 부록 B에서 `_is_total_row`를 항상 True로 바꿨다. **68개 실행, 실패 0, 오류 0, skip 0**. 같은 IS 안의 매출 분해 행만 넣은 재현에서는 정상 코드가 `not_found`, 변이 코드가 `account_id`로 고른다.
- 제안: 같은 허용 재무제표와 같은 ID 아래에 합계 10·분해 99를 같이 넣어 10을 반환하는지, 분해 행만 있으면 반환하지 않는지 검사한다. 이 필터 제거 변이도 함정 검사에 넣는다. 기존 7개 변이 통과만으로 모든 중요한 규칙이 검사됐다고 해석하지 않는다.

### R4 — 중요: 이름 대체가 다른 표준 계정의 의미를 덮어쓸 수 있음

- 위치: `dart_review/accounts.py:90`, `accounts.py:96`, `accounts.py:98`, `dart_review/compare.py:114`.
- 유형: **합성 행에서 재현한 정책 위험. 현재 72건에서 이 잘못된 순이익 선택이 관찰된 것은 아니다.**
- 근거: 대상 순이익 ID가 없고 `account_nm=당기순이익`, `account_id=ifrs-full_ProfitLossAttributableToOwnersOfParent`인 행 하나를 주면 `account_name`으로 선택한다(부록 B `conflicting_standard_id_name`). 회사 전체 당기순이익과 지배기업 소유주 귀속 이익의 범위 차이를 이름이 덮어쓴다. 후속 비교에서는 이름으로 찾았다는 메모만 추가한다.
- 제안: 미사용/빈 ID의 정확한 이름 대체와, 의미가 다른 유효 표준 ID의 충돌을 구분한다. 충돌에 대한 근거 있는 매핑이 없으면 `확인 필요` 또는 모호함으로 처리한다. 카카오의 현재 6건처럼 캐시에서 확인한 충돌과 이를 검증한 근거는 명시적으로 관리하되, 모든 충돌에 이름을 무조건 우선하는 일반 규칙으로 확대하지 않는다. 이 변경을 채택한다면 dev06의 판정 기준도 근거를 검토하고 일관되게 확정해야 한다.

### R5 — 중요: 통화가 둘 다 없으면 '같은 통화'로 처리함

- 위치: `dart_review/facts.py:91`, `facts.py:96`, `dart_review/compare.py:88`, `compare.py:127`; `tests/test_rules.py:195`.
- 유형: **합성 Fact에서 재현. 현재 개발용 대상 행은 모두 KRW다.**
- 실행 결과: 같은 계정·같은 길이의 100 → 120에서 두 Fact의 `currency=None`이면 `비교 가능`, 변화 20, 변화율 20.00이다(부록 B `currency_missing`). `None != None`이 False라 검사가 끝난다. 빈 문자열 두 개도 같은 구조다.
- 문제: 통화 정보가 없다는 것이 같은 통화의 확인은 아니다. SCOPE의 “같은 통화일 때만 비교” 보장에 빈틈이 있다.
- 제안: 양쪽 통화가 유효한 문자열로 확인되었는지 먼저 검사한다. 미확인은 검증 오류 또는 `확인 필요`로 처리하고 근거 없는 통화 기본값을 채우지 않는다. `find_restatements`의 같은 값 그룹 키(`compare.py:47`)에도 통화 검증이 필요하다. 현재 데이터의 정답 재계산 결과에는 영향이 없었다.

### R6 — 사소: '두 보고서 사이에 재작성이 접수됨'과 실제 조건이 다름

- 위치: `dart_review/compare.py:123`, `compare.py:125`, `dart_review/review.py:29`, `tests/test_rules.py:225`.
- 유형: **합성 접수번호 경계 재현**.
- 근거: 비교 보고서 접수번호가 20241114…와 20251114…일 때, 차이가 확인된 보고서 두 개를 20231001…·20260317…로 주어도 `확인 필요`가 나온다. 코드는 `earlier < last and later > first`, 즉 두 구간이 겹치는지를 본다. 나중 관찰 보고서가 비교 보고서 사이에 접수됐는지를 검사하는 것은 아니다.
- 제안: 이 보수적 경고 자체가 반드시 틀린 것은 아니다. 두 관찰 사이 실제 변경 시점을 모르는 경우도 있으므로, “접수됨” 대신 “관찰 구간이 겹쳐 변경 시점을 특정할 수 없음”으로 근거를 적거나, 정말 접수 시점을 경계로 삼는다면 조건과 문서를 맞춘다. 전체 구간을 감싸는 경우·경계와 같은 경우·양 끝 바깥인 경우를 테스트한다. dev08은 실제 변경 관찰 보고서가 비교 두 보고서 사이에 있어 이 문제 때문에 오답인 것은 아니다.

### R7 — 사소: 최신 정정본·원래 공시 값이라는 표현의 근거 범위가 과장됨

- 위치: `docs/DATA_NOTES.ko.md:51`, `:55`; `docs/SCOPE.ko.md:50`; `eval/build_gold.py:141`; dev07.
- 유형: **실제 재무 캐시와 카카오 list 캐시 대조**.
- 근거: `cache/list.json/923165322f64f2be96bbcacff1deb055.meta.json`은 조회 범위가 20230401~20250430이다. 본문은 22건·1페이지이며 해시 검증을 통과했다. 카카오 2023~2024의 8개 보고서 × 연결/별도 16개 응답은 이 조회 범위 안 마지막 정정 접수번호와 모두 일치했다.
- 한계: 이 목록만으로 2026-10-07 수집 시점까지 더 늦은 정정이 전혀 없었음이나 모든 회사에 대한 API 최신본 반환 계약을 증명하지 못한다. 최신본이라는 일반 API 동작은 이번 로컬 검토로 확인하지 않았다.
- 특히 dev07의 460,212,161,525는 접수번호 `20250324000901`의 **[기재정정]사업보고서 (2024.12)** 값이다. 최초 사업보고서 접수번호는 `20250318001297`이며 그 최초 본문 금액은 이 검토에서 확인하지 않았다.
- 제안: “조회 범위 안 마지막 정정과 일치”라고 관찰을 제한하고, `base_as_originally_reported`는 “2024 사업보고서 캐시 값(기재정정본)”처럼 명확히 표기한다. 정정 공시와 다른 보고서의 비교값 변경을 같은 사건으로 단정하지 않는다. 값 차이는 입증됐지만 그 회계적 원인은 미확인이다.

### R8 — 사소: 문서의 기간·반올림 표현에 예외/자리수 혼동이 있음

- 위치: `docs/DATA_NOTES.ko.md:15`, `:73`; `docs/GOLD_RULES.ko.md:37`; `dart_review/periods.py:104`, `:127`.
- 근거: 1분기 CF의 연초 누적은 그 자체로 1~3월 3개월이며 코드도 이를 제공한다. “CF는 3개월 값 없음”이라는 문장은 2·3분기 단독 3개월과 구별해야 한다. 또한 코드의 ROUND_HALF_UP/0.01은 소수 둘째 자리까지 보존하지만 문서의 “소수 둘째 자리에서 반올림”은 한 자리까지로 읽힐 수 있다.
- 제안: “1분기는 누적=3개월, 반기·3분기는 단독 분기 CF 칸 없음”, “소수 셋째 자리에서 반올림해 둘째 자리까지 표시; ±0.005는 0에서 멀어지는 방향”으로 적는다. 현재 dev03/dev10 수치가 잘못됐다는 뜻은 아니다.

## C. DATA_NOTES 주장 재확인

| 주장 | 이번 독립 확인 | 해석/보완 |
|---|---|---|
| 1분기 손익 당기=누적 | 매출·영업이익·순이익 각각 18/18 | 3회사 × 2기준 × 3년 |
| 반기 누적=1분기 누적+2분기 3개월 | 각 계정 18/18 | 세 계정 54건 |
| 3분기 누적=반기 누적+3분기 3개월 | 각 계정 18/18 | 두 누적 합산 식 합계 108건 |
| 연간 손익 thstrm_add가 비거나 당기와 같음 | 각 계정 18/18 | 빈 칸을 필수 금액으로 읽지 않아야 함 |
| 반기·3분기 CF 기초 현금=BS 전년 말 현금 | 32/33, 3건 제외 | 문서의 1건 불일치와 동일 |
| CF 전년 비교칸=전년 동종 보고서 당기 | **36/36** | 3회사 × 2기준 × 2비교연도 × 3보고서. 문서의 12/12는 보고서 종류별이면 맞지만 분모 범위가 적혀 있지 않다 |
| 분기 BS 전기=전년 사업보고서 기말 자산·부채 | 72/72 | 금액 관계와 기간 칸 선택 모두 대조 |
| 대상 432계정의 해석 | 표준 ID 426, 이름 6 | 이름 6건 모두 카카오 2023 세 중간보고서 × 연결/별도 매출 |
| 카카오 매출 ID | 6건 모두 GrossProfit / 영업수익 | 데이터의 ID·이름 충돌을 확인. 제출자가 왜 그렇게 표시했는지는 미확인 |
| 같은 대상 재무제표 내 해당 ID 중복 | 대상 6개 계정에서 자동 선택 충돌 없음 | 전체 모든 계정의 중복을 보장한 검사는 아님 |
| 최신 정정본 주장 | 제한된 목록 내 16/16 일치 | R7의 범위 한계 적용 |

기초 현금 불일치는 카카오 2023 반기 연결: CF 4,835,909,162,298, BS 전년 말 4,780,244,024,656이다. BS 표준 현금 ID가 없어 이 검사를 건너뛴 세 경우는 카카오 연결 2023 3분기, 2024 반기, 2024 3분기다. 이 관찰과 현금흐름표 칸의 연도 간 일치가 누적 해석을 뒷받침한다. 기초 현금 한 항목의 일치만으로 모든 CF 행의 회계적 기간 의미를 완전히 증명한 것은 아니다.

재작성 표의 독립 계산:

| 값 | 앞 보고서 | 뒤 보고서 비교칸 | 차이 | 변화율 |
|---|---:|---:|---:|---:|
| Kakao 2023 Q3 revenue CFS | 2,160,931,354,165 | 2,011,471,714,310 | -149,459,639,855 | -6.92% |
| Kakao 2024 operating income CFS | 460,212,161,525 | 495,277,757,353 | 35,065,595,828 | 7.62% |
| Kakao 2024 revenue CFS | 7,871,692,199,887 | 7,864,033,326,475 | -7,658,873,412 | -0.10% |
| Celltrion 2023 end assets CFS | 19,917,534,297,169 | 19,956,813,831,274 | 39,279,534,105 | 0.20% |
| Celltrion 2023 end liabilities OFS (dev08) | 2,230,608,519,706 | 2,256,044,979,595 | 25,436,459,889 | 1.14% |

문서 4절의 네 수치와 변화율은 모두 일치했다. 이는 같은 명목 기간 수치의 차이 확인이며, 오류 수정·분류 변경·중단영업·합병 등 구체적 원인은 이번 자료로 확정할 수 없다.

## D. 규칙 논리와 판단이 갈리는 정답

`periods.py`의 IS/CIS/CF/BS 칸 배치는 이 개발용 12월 결산 자료의 1분기·반기·3분기·사업보고서와 모순을 찾지 못했다. 1분기에는 손익 및 CF의 3개월과 누적이 같은 기간이다. 4분기 손익 3개월과 반기/3분기 CF의 단독 분기값을 차감 계산하지 않는 것은 계산 불능 사실이 아니라 **현재 제품의 보수적 지원 범위 선택**이다. 다른 결산월이나 원문 주석까지 검증한 결과로 확대할 수 없다.

`compare.py`에서 구조적으로 잘못된 비교 → 계정 모호함 → 금액 없음 → 재작성 경고 → 비교 계산의 순서는 대체로 일관된다. 구조 불일치와 결측이 동시에 있으면 먼저 발견된 거절만 반환한다는 계약을 명시하면 된다. 다만 R1의 점검 미완료, R5의 통화 미확인은 이 순서에 들어 있지 않다. 현재 회계적 의미를 확인하지 못한 상황을 단순 메모로만 소비하지 않도록 해야 한다.

| 결정 | 의견 | 이유와 대안 |
|---|---|---|
| 연결·별도 언급 없으면 연결 | **조건부 동의** | 범위의 회사에 대한 제품 기본값으로 일관되다. 답변에서 연결 기본값을 명시해야 한다. 연결 자료가 없을 때 별도로 조용히 바꾸면 안 된다. '일반 관행'이라는 이유만으로 모든 사용자 의도를 확정할 수는 없다. |
| dev05: 연결·별도 차액까지 금지 | **전면 금지에는 비동의** | 두 금액 차이는 95,562,929,000,000원, 약 95.6조 원이다. 같은 기간·통화와 서로 다른 집계 범위를 명시해 '연결 매출이 별도보다 그만큼 크다'고 말하는 산술은 가능하다. 이를 전년 성장·영업 개선·자회사 매출 자체로 해석하면 안 된다. 현 제품은 병렬 표시만 지원하도록 유지할 수 있지만 단순 차액 문장까지 회계 오류로 채점해서는 안 된다. 원인 설명은 현재 데이터만으로 확정하지 않는다. |
| dev07: 47.80%를 기본값, 59.07%를 메모 | **조건부 동의** | 같은 2025 보고서의 당기 732,036,535,379와 전기 495,277,757,353을 사용한 비교다. 2024 보고서 캐시의 460,212,161,525를 쓰면 59.07%다. 질문이 '당시 발표 수치 기준'이라면 다른 작업이므로 그 기준을 다시 명시해야 한다. '원래 값'은 R7처럼 정정본임을 밝혀야 한다. |
| dev08: 2023년 말 차이로 2024년 3분기말 비교에 확인 필요 | **조건부 동의** | 보수적 경고는 가능하다. 직접 관찰한 것은 2023년 말 부채 비교값 차이이며, 2024-09-30 금액 자체의 재작성을 확인한 것은 아니다. 이유는 '과거 비교값 불일치가 관찰되어 이번 기간 영향 미확인'으로 한정한다. '이번 비교의 기준이 실제로 다르다'고 단정하는 답변은 오답이다. |
| dev12: 이익을 되묻기 | **동의** | 계정 6개 범위에서도 영업이익과 당기순이익 두 후보가 있다. 특정 계정을 임의로 정할 증거가 없다. |
| 두 자리 HALF_UP·부호 전환 변화율 생략 | **동의, 문구 보완** | 재현 가능한 표시 정책이다. 양수 기준 0 도달이면 -100.00%는 정의되며 코드도 그렇게 계산한다. 음수 기준의 변화율 생략은 수학적 불가능이 아니라 오해 방지 정책이다. 음수/0 경계와 반올림 자리수는 R8처럼 명시한다. |

주의: dev05의 단순 차액을 허용하기로 결정하더라도 같은 기간 CFS/OFS를 시간 변화용 `compare()`에 그대로 넣어 `비교 가능`으로 만드는 수정은 적절하지 않다. 병렬 설명의 산술과 시간 변화 계산을 구분해야 한다.

## E. 빠진 함정과 테스트 보완 우선순위

기존 12건을 폐기할 필요는 없다. 다음은 1-4 전에 평가 계약과 규칙 테스트에 추가할 가치가 있는 경우다. 새로운 회사 자료나 모델 호출 없이 기존 개발 캐시 또는 작은 합성 응답으로 만들 수 있다.

1. **불완전한 검증:** 중간 사업보고서 미캐시·013·대상 계정 없음·중복/모호함. R1의 세 분기를 먼저 고정한다.
2. **근거 자체가 틀린 정답:** dev08 재작성 쌍이 서로 다른 기간/기준/통화이거나 사유와 접수번호가 다름. 기간 라벨과 실제 셀의 기간도 독립 비교한다.
3. **계정 선택:** 같은 허용 재무제표 안의 합계/분해, ID·이름 충돌, 전체 순이익/지배주주 귀속 순이익, 같은 ID가 IS/CIS에서 서로 다른 값인 상황. 무조건 잘못된 값을 골랐다고 단정하기 전에 적용할 우선순위·경고 정책을 정한다.
4. **기간 표현:** 1분기 CF는 제공 가능, 2·3분기 단독 CF/4분기 단독 손익은 현재 미지원, 반기 3개월과 누적 6개월, 같은 해 분기 간 비교에서 재작성 근거가 겹치지 않음. dev06이 마지막 유형을 통과해도 기준 변경이 없었다는 증명은 아니다.
5. **통화·변화율:** 양쪽 통화 없음, 기준 0, 양→음/음→양/음→음/음→0, +0.005와 -0.005의 반올림 경계. 실제 CF 음수는 손익의 흑자/적자와 같은 말로 표시하지 않는다.
6. **범위와 원인:** 연결 범위 변화·합병 등으로 큰 변화가 나는 경우, 수치 차이만으로 성장 이유를 확정하지 않음. 순이익에서 지배주주/비지배주주 귀속을 합계와 혼동하지 않음.
7. **질문 커버리지:** 12건 중 단독 OFS 정상 비교는 dev08의 경고 상황과 겹친다. 정상 OFS 비교, 반기/1분기 해석, 순수 '계정ID 미사용'(현재 dev06은 '다른 표준 ID 오표기')을 분리하면 실패 원인을 더 잘 식별할 수 있다. sealed 회사는 사용하지 않는다.

`tests/test_gold.py:80`의 유형 커버리지는 `case_types` 태그가 있다는 것만 확인한다. 질문이 실제로 그 함정을 시험하는지까지 자동 입증하지 않는다. `cross_check()`의 clarify 분기는 즉시 빈 목록을 반환하므로 dev12가 질문 해석기를 통과했다는 증거도 아니다. 아직 1-4 이전이라는 범위를 명확히 유지해야 한다.

## F. 실행한 검증과 제한

저장소 루트에서 실행한 기존 검증:

```text
python3 -m unittest discover -s tests -v
Ran 68 tests ... OK

python3 eval/build_gold.py --check
12 answers agree with the rules; dev_gold.json is up to date

python3 scripts/check_trap_tests.py
원래 규칙: 11개 중 실패 0개
지정한 7개 변이: 모두 해당 함정 테스트에서 잡힘
```

별도 임시 디렉터리에서 작성·실행한 코드:

```text
python3 "$audit_dir/independent_audit.py" .
12개 사례 대조 불일치 0; IMPORTS_DART_REVIEW False
현금흐름 전년 비교 36/36, BS 전기 72/72, 합계 해석 ID 426/이름 6

python3 "$audit_dir/probes.py" .
R1: 정상 확인 필요 → bridge 없음/013/빈 계정 비교 가능
R2: 다른 기간 restated_pair의 cross_check_problems=[]
R3: 합계 필터 제거 후 기존 68개 전부 통과
R4: 다른 의미의 표준 ID 행을 account_name으로 선택
R5: 통화 둘 다 None이어도 비교 가능, 20/20.00%
R6: 비교 구간을 감싸는 재작성 관찰 구간에도 확인 필요
network_requests=0 (실제 캐시를 사용하는 검토 클라이언트)
```

직접 확인한 것:

- 요청된 문서, 규칙, 질문, 정답 생성기, 정답 JSON, 테스트와 함정 검사 소스.
- 허용된 재무 캐시 73개, 카카오 공시목록 캐시 1개 및 본문 해시.
- 12건의 금액/상태 해석, 선택한 근거와 독립 산술, 데이터 조사 표의 위 항목.
- 기존 검증 결과와 추가 경계 재현. 메모리 변이 결과를 원본 테스트 결과와 구별했다.
- 추적 파일 32개의 검토 시작/보고서 저장 전 SHA-256 동일성, 최종 Git diff 무변경.

직접 확인하지 못했거나 이번 범위에서 수행하지 않은 것:

- 공시 원문·주석에 따른 값 변경의 회계적 원인, 특정 분기말에 영향을 줬는지, 원본 표의 공식 정정 전후 비교.
- 2025-04-30 이후 카카오 정정 목록, 최신 서버의 반환 보장, 봉인 회사·다른 결산월의 일반화.
- 실제 인증키를 읽는 공개 안전성 검사. `check_public_safety.py`의 기본 동작은 키를 읽으므로 이 검토에서 기본 명령으로 실행하지 않았다. 기존 테스트 내부의 가짜 키·임시 저장소 검사는 실행됐다.
- 아직 없는 자연어 해석기·채점기·LLM 전체 흐름의 성능. 68개 테스트와 12개 정답 일치는 Agent 성능 점수가 아니다.

현재 상태: 1-2·1-3 독립 검토 완료. 추적 코드 수정 없음.
사용자가 지금 할 일: Claude에 이 보고서를 전달해 R1~R8의 수용/보류와 이유를 항목별로 기록하도록 한다.
다음 작업: R1~R3 및 상태·정답 정책을 우선 정리한 뒤 1-4 평가 실행기를 진행한다.
추가 프롬프트 필요 여부: 새 장문 프롬프트는 불필요. “docs/reviews/1-3_codex_result.ko.md를 읽고 항목별 반영 여부·근거·변경 범위를 정리해줘”로 이어갈 수 있다. 이 검토가 추적 파일 수정 승인을 대신하지는 않는다.

## G. 사례별 원본 근거

아래 `.body` 경로는 모두 `cache/fnlttSinglAcntAll.json/` 아래다. 같은 stem의 `.meta.json`으로 회사·연도·보고서·연결/별도를 확인할 수 있다. 부록 A는 해시와 이 정보까지 대조한다.

| 사례/역할 | .body 파일명 | 접수번호 | 재무제표 / 계정 ID | 칸 |
|---|---|---|---|---|
| dev01/current | `df6d85a2516eac12b55f7e77da94b04c.body` | 20260310002820 | IS / `ifrs-full_Revenue` | `thstrm` |
| dev01/base | `df6d85a2516eac12b55f7e77da94b04c.body` | 20260310002820 | IS / `ifrs-full_Revenue` | `frmtrm` |
| dev02/current | `6bf02f83d387577fb495f6c5eaa70c5b.body` | 20251114002447 | BS / `ifrs-full_Assets` | `thstrm` |
| dev02/base | `5aa76ef703b880e15b13701aed9baedf.body` | 20241114002642 | BS / `ifrs-full_Assets` | `thstrm` |
| dev03/current | `6bf02f83d387577fb495f6c5eaa70c5b.body` | 20251114002447 | CF / `ifrs-full_CashFlowsFromUsedInOperatingActivities` | `thstrm` |
| dev03/base | `6bf02f83d387577fb495f6c5eaa70c5b.body` | 20251114002447 | CF / `ifrs-full_CashFlowsFromUsedInOperatingActivities` | `frmtrm_q` |
| dev04/current | `d27dc570d17f0176b8ceebbee8387ae7.body` | 20251114002699 | IS / `dart_OperatingIncomeLoss` | `thstrm_add` |
| dev04/base | `d27dc570d17f0176b8ceebbee8387ae7.body` | 20251114002699 | IS / `dart_OperatingIncomeLoss` | `frmtrm_add` |
| dev05/CFS | `df6d85a2516eac12b55f7e77da94b04c.body` | 20260310002820 | IS / `ifrs-full_Revenue` | `thstrm` |
| dev05/OFS | `7cd00a8999fca41c9581e64b7896cfab.body` | 20260310002820 | IS / `ifrs-full_Revenue` | `thstrm` |
| dev06/current | `d3bda970e8ad8b159ca7ec8c7f09d60e.body` | 20231226000387 | CIS / `ifrs-full_GrossProfit` | `thstrm` |
| dev06/base | `2d7f73b17e1a119aa4cb1e7328ad74ba.body` | 20230921000228 | CIS / `ifrs-full_GrossProfit` | `thstrm` |
| dev07/current | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | CIS / `dart_OperatingIncomeLoss` | `thstrm` |
| dev07/base | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | CIS / `dart_OperatingIncomeLoss` | `frmtrm` |
| dev08/current | `5ecdc2b2847ba1cee7f1c82bc4c6ce49.body` | 20251114002699 | BS / `ifrs-full_Liabilities` | `thstrm` |
| dev08/base | `80e394cb45517a23e56f3dd9193d1e64.body` | 20241114002862 | BS / `ifrs-full_Liabilities` | `thstrm` |
| dev09/current | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | CIS / `ifrs-full_ProfitLoss` | `thstrm` |
| dev09/base | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | CIS / `ifrs-full_ProfitLoss` | `frmtrm` |

재작성 확인에 추가로 사용한 근거:

| 값/역할 | .body 파일명 | 접수번호 | 칸 |
|---|---|---|---|
| Kakao 2023 Q3 revenue CFS / old | `d3bda970e8ad8b159ca7ec8c7f09d60e.body` | 20231226000387 | `thstrm` |
| Kakao 2023 Q3 revenue CFS / new | `f674fc495c421ce48ac13af736b0914c.body` | 20241226000456 | `frmtrm_q` |
| Kakao 2024 operating income CFS / old | `823cb7ab3291514503e7e23109732ce5.body` | 20250324000901 | `thstrm` |
| Kakao 2024 operating income CFS / new | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | `frmtrm` |
| Kakao 2024 revenue CFS / old | `823cb7ab3291514503e7e23109732ce5.body` | 20250324000901 | `thstrm` |
| Kakao 2024 revenue CFS / new | `d85827831f766aba4d9b091eb1556fd3.body` | 20260318001423 | `frmtrm` |
| Celltrion 2023 end assets CFS / old | `b657b2472ecf7540a2f00dcbf27e013f.body` | 20240318000913 | `thstrm` |
| Celltrion 2023 end assets CFS / new | `3bb84c8c1e4703d765ee3d01f9d81513.body` | 20250317000929 | `frmtrm` |
| Celltrion 2023 end liabilities OFS (dev08) / old | `80e394cb45517a23e56f3dd9193d1e64.body` | 20241114002862 | `frmtrm` |
| Celltrion 2023 end liabilities OFS (dev08) / new | `fb9360502fafc244d36d8b15780ac15f.body` | 20250317000929 | `frmtrm` |

## 부록 A. 독립 계산 코드

아래 코드를 임시 디렉터리의 `independent_audit.py`로 저장하고 저장소 루트에서 `python3 <그 경로> .`로 실행한다. 결과 JSON은 코드가 있는 임시 디렉터리에만 저장된다. 모델 호출·API 요청·키 읽기·생산 코드 import가 없다. 출력 파일에는 로컬 경로가 포함될 수 있으므로 임시 결과를 그대로 공개 저장소에 추가할 필요는 없다.

<!-- independent-audit-code -->
```python
"""Offline audit. Intentionally imports neither dart_review nor build_gold."""
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).parent
ALLOWED = {'00126380', '00258801', '00413046'}
REPORTS = ('11013', '11012', '11014', '11011')
DB = {}
for p in sorted((ROOT / 'cache/fnlttSinglAcntAll.json').glob('*.meta.json')):
    meta = json.loads(p.read_text())
    q = meta['params']
    if q.get('corp_code') not in ALLOWED:
        continue
    body_path = p.with_name(p.name.replace('.meta.json', '.body'))
    raw = body_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == meta['sha256']
    key = (q['corp_code'], int(q['bsns_year']), q['reprt_code'], q['fs_div'])
    assert key not in DB
    DB[key] = (json.loads(raw), meta, str(body_path.relative_to(ROOT)))

def rows(corp, year, report, basis='CFS'):
    return DB[corp, year, report, basis][0].get('list', [])

def cell(corp, year, report, stmt, account, col, basis='CFS'):
    body, meta, path = DB[corp, year, report, basis]
    found = [r for r in body['list'] if r.get('sj_div') == stmt
             and r.get('account_id') == account and r.get('account_detail') == '-']
    assert len(found) == 1, (corp, year, report, basis, stmt, account, len(found))
    r = found[0]
    return dict(amount=int(r[col + '_amount'].replace(',', '')), rcept_no=r['rcept_no'],
                column=col, sj_div=stmt, account_id=account, account_nm=r['account_nm'],
                response_sha256=meta['sha256'], cache=path, year=year, report_code=report,
                fs_div=basis, currency=r['currency'])

def pct(new, old):
    if old <= 0 or new < 0:
        return None
    numerator = (new - old) * 10000
    whole, rem = divmod(abs(numerator), old)
    rounded = whole + (2 * rem >= old)
    sign = '-' if numerator < 0 else ''
    return f'{sign}{rounded // 100}.{rounded % 100:02d}'

# These selections were written from the natural-language questions and raw
# statement meanings, before reading dev_gold values. No expected cells imported.
S, K, C = '00126380', '00258801', '00413046'
REV, OP, NET = 'ifrs-full_Revenue', 'dart_OperatingIncomeLoss', 'ifrs-full_ProfitLoss'
CF, ASSET, LIAB = 'ifrs-full_CashFlowsFromUsedInOperatingActivities', 'ifrs-full_Assets', 'ifrs-full_Liabilities'
PAIRS = {
 'dev01': ((S,2025,'11011','IS',REV,'thstrm'), (S,2025,'11011','IS',REV,'frmtrm')),
 'dev02': ((S,2025,'11014','BS',ASSET,'thstrm'), (S,2024,'11014','BS',ASSET,'thstrm')),
 'dev03': ((S,2025,'11014','CF',CF,'thstrm'), (S,2025,'11014','CF',CF,'frmtrm_q')),
 'dev04': ((C,2025,'11014','IS',OP,'thstrm_add'), (C,2025,'11014','IS',OP,'frmtrm_add')),
 'dev06': ((K,2023,'11014','CIS','ifrs-full_GrossProfit','thstrm'), (K,2023,'11012','CIS','ifrs-full_GrossProfit','thstrm')),
 'dev07': ((K,2025,'11011','CIS',OP,'thstrm'), (K,2025,'11011','CIS',OP,'frmtrm')),
 'dev08': ((C,2025,'11014','BS',LIAB,'thstrm','OFS'), (C,2024,'11014','BS',LIAB,'thstrm','OFS')),
 'dev09': ((K,2025,'11011','CIS',NET,'thstrm'), (K,2025,'11011','CIS',NET,'frmtrm')),
}
answers = []
restated_base_old = cell(C,2024,'11014','BS',LIAB,'frmtrm','OFS')
restated_base_new = cell(C,2024,'11011','BS',LIAB,'frmtrm','OFS')
assert restated_base_old['currency'] == restated_base_new['currency'] == 'KRW'
restatement_observed = restated_base_old['amount'] != restated_base_new['amount']
for ident, pair in PAIRS.items():
    new, old = (cell(*args) for args in pair)
    delta = new['amount'] - old['amount']
    direction = '흑자 전환' if ident == 'dev09' else ('증가' if delta > 0 else '감소' if delta < 0 else '변동 없음')
    # Both cells are the same statement measure, currency, and requested period length.
    assert new['currency'] == old['currency'] == 'KRW'
    needs_review = ident == 'dev08' and restatement_observed and old['rcept_no'] < restated_base_new['rcept_no'] < new['rcept_no']
    answers.append(dict(id=ident, status='확인 필요' if needs_review else '비교 가능',
                        current=new, base=old, change=delta, change_pct=pct(new['amount'],old['amount']), direction=direction))
answers.append(dict(id='dev05',status='비교 불가', CFS=cell(S,2025,'11011','IS',REV,'thstrm'),
                    OFS=cell(S,2025,'11011','IS',REV,'thstrm','OFS')))
cf_row = next(r for r in rows(S,2025,'11014') if r['sj_div']=='CF' and r['account_id']==CF)
assert {k for k in cf_row if k.endswith('_amount')} == {'thstrm_amount','frmtrm_q_amount'}
answers.append(dict(id='dev10',status='비교 불가', rationale='No direct July-September CF field; subtraction intentionally outside product scope'))
body, meta, path = DB[S,2014,'11011','CFS']
assert body['status'] == '013'
answers.append(dict(id='dev11',status='데이터 없음',api_status=body['status'],cache=path, response_sha256=meta['sha256']))
answers.append(dict(id='dev12',action='clarify',options=['operating_income','net_income'],rationale='Question does not choose either profit measure'))
def annual(y): return f'{y}-01-01~{y}-12-31 (누적 12개월)'
def nine(y): return f'{y}-01-01~{y}-09-30 (누적 9개월)'
def q3(y): return f'{y}-07-01~{y}-09-30 (3개월)'
period_labels = {
 'dev01':(annual(2025),annual(2024)), 'dev02':('2025-09-30 시점','2024-09-30 시점'),
 'dev03':(nine(2025),nine(2024)), 'dev04':(nine(2025),nine(2024)),
 'dev06':(q3(2023),'2023-04-01~2023-06-30 (3개월)'), 'dev07':(annual(2025),annual(2024)),
 'dev08':('2025-09-30 시점','2024-09-30 시점'), 'dev09':(annual(2025),annual(2024)),
 'dev10':(q3(2025),q3(2024)), 'dev11':(annual(2014),annual(2013))}
for a in answers:
 if a['id'] in period_labels: a['current_period'],a['base_period']=period_labels[a['id']]
 if a['id']=='dev05': a['period']=annual(2025)
answers.sort(key=lambda a:a['id'])
gold = {a['id']:a for a in json.loads((ROOT/'eval/dev_gold.json').read_text())['answers']}
for a in answers:
    g=gold[a['id']]
    mismatches=[]
    for field in ('status','change','change_pct','direction','action','current_period','base_period','period'):
        if field in a and a[field] != g.get(field): mismatches.append(field)
    for role in ('current','base','CFS','OFS'):
        if role in a:
            for field in ('amount','rcept_no','column','sj_div','account_id','account_nm','response_sha256','year','report_code','fs_div','currency'):
                if a[role][field] != g['values'][role][field]: mismatches.append(role+'.'+field)
    a['gold_mismatches']=mismatches

# Independent account inventory using constrained exact known names only when ID absent.
TARGETS = [(REV,('IS','CIS'),('매출액','영업수익','수익(매출액)')),
 (OP,('IS','CIS'),('영업이익','영업이익(손실)')),
 (NET,('IS','CIS'),('당기순이익','당기순이익(손실)','반기순이익','분기순이익','분기순이익(손실)')),
 (CF,('CF',),('영업활동현금흐름','영업활동으로인한현금흐름')),
 (ASSET,('BS',),('자산총계',)), (LIAB,('BS',),('부채총계',))]
resolved={}; methods=collections.Counter(); named=[]
for key,(body,meta,path) in DB.items():
    if body['status'] != '000': continue
    for account, statements, names in TARGETS:
        pool=[r for r in body['list'] if r['sj_div'] in statements and r.get('account_detail') == '-']
        hits=[r for r in pool if r['account_id'] == account]
        if hits:
            # IS/CIS can repeat the same total; expose all statement values if distinct.
            hits.sort(key=lambda r:statements.index(r['sj_div'])); method='id'
        else:
            hits=[r for r in pool if ''.join(r.get('account_nm','').split()) in names]; method='name'
        assert hits, (key, account)
        chosen=hits[0]
        assert sum(r['sj_div']==chosen['sj_div'] for r in hits)==1
        resolved[key+(account,)]=chosen;methods[method]+=1
        if method=='name': named.append(dict(key=key, account=account, raw_id=chosen['account_id'], name=chosen['account_nm']))

def amount(key,account,col):
    return int(resolved[key+(account,)][col+'_amount'].replace(',',''))

checks={}
def check(label,records):
    checks[label]=dict(passed=sum(bool(v) for _,v in records), total=len(records),failures=[k for k,v in records if not v])
for acc in (REV,OP,NET):
    q1=[]; q2=[]; q3=[];annual=[]
    for corp in sorted(ALLOWED):
        for basis in ('CFS','OFS'):
            for year in (2023,2024,2025):
                ks=[(corp,year,r,basis) for r in REPORTS]; label=(corp,year,basis,acc)
                q1.append((label,amount(ks[0],acc,'thstrm')==amount(ks[0],acc,'thstrm_add')))
                q2.append((label,amount(ks[1],acc,'thstrm_add')==amount(ks[0],acc,'thstrm_add')+amount(ks[1],acc,'thstrm')))
                q3.append((label,amount(ks[2],acc,'thstrm_add')==amount(ks[1],acc,'thstrm_add')+amount(ks[2],acc,'thstrm')))
                row=resolved[ks[3]+(acc,)];annual.append((label,row.get('thstrm_add_amount','') in ('',row['thstrm_amount'])))
    for label, recs in [('q1',q1),('q2',q2),('q3',q3),('annual',annual)]: check(label+'_'+acc,recs)
cfprior=[];bsprior=[];cash=[];cash_missing=[]
for corp in sorted(ALLOWED):
 for basis in ('CFS','OFS'):
  for year in (2023,2024,2025):
   for report in REPORTS[:3]:
    key=corp,year,report,basis
    if year>2023:
     cfprior.append((key,amount(key,CF,'frmtrm_q')==amount((corp,year-1,report,basis),CF,'thstrm')))
     for acc in (ASSET,LIAB):
      bsprior.append((key+(acc,),amount(key,acc,'frmtrm')==amount((corp,year-1,'11011',basis),acc,'thstrm')))
    if report not in ('11012','11014'):continue
    rr=rows(*key[:3],basis=basis)
    opening=[r for r in rr if r['sj_div']=='CF' and r['account_id']=='dart_CashAndCashEquivalentsAtBeginningOfPeriodCf']
    balance=[r for r in rr if r['sj_div']=='BS' and r['account_id']=='ifrs-full_CashAndCashEquivalents']
    if len(opening)!=1 or len(balance)!=1:
     cash_missing.append(dict(key=key,opening_count=len(opening),balance_count=len(balance)));continue
    c0=int(opening[0]['thstrm_amount']);b0=int(balance[0]['frmtrm_amount'])
    cash.append((dict(key=key,cf=c0,bs=b0),c0==b0))
check('cf_prior',cfprior);check('bs_prior',bsprior);check('cf_opening_vs_bs_prior',cash)
restated=[
 dict(label='Kakao 2023 Q3 revenue CFS',old=cell(K,2023,'11014','CIS','ifrs-full_GrossProfit','thstrm'),new=cell(K,2024,'11014','CIS',REV,'frmtrm_q')),
 dict(label='Kakao 2024 operating income CFS',old=cell(K,2024,'11011','CIS',OP,'thstrm'),new=cell(K,2025,'11011','CIS',OP,'frmtrm')),
 dict(label='Kakao 2024 revenue CFS',old=cell(K,2024,'11011','CIS',REV,'thstrm'),new=cell(K,2025,'11011','CIS',REV,'frmtrm')),
 dict(label='Celltrion 2023 end assets CFS',old=cell(C,2023,'11011','BS',ASSET,'thstrm'),new=cell(C,2024,'11011','BS',ASSET,'frmtrm')),
 dict(label='Celltrion 2023 end liabilities OFS (dev08)',old=cell(C,2024,'11014','BS',LIAB,'frmtrm','OFS'),new=cell(C,2024,'11011','BS',LIAB,'frmtrm','OFS'))]
for a in restated: a['change']=a['new']['amount']-a['old']['amount'];a['change_pct']=pct(a['new']['amount'],a['old']['amount'])
result=dict(financial_cache_count=len(DB),answers=answers,checks=checks,methods=dict(methods),name_matches=named,
            cash_missing=cash_missing,restatements=restated)
(OUT/'independent_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for a in answers:
 print(a['id'],a.get('status',a.get('action')),a.get('current',{}).get('amount',a.get('CFS',{}).get('amount')),
       a.get('base',{}).get('amount',a.get('OFS',{}).get('amount')),a.get('change'),a.get('change_pct'),a['gold_mismatches'])
print('CHECKS',json.dumps(checks,ensure_ascii=False))
print('METHODS',dict(methods),'CASH_MISSING',cash_missing)
print('IMPORTS_DART_REVIEW',any(n.startswith('dart_review') for n in sys.modules))
```

## 부록 B. 결함·테스트 약점 재현 코드

아래 `probes.py`는 제품 코드를 호출하되 오프라인 캐시만 사용한다. 잘못된 입력과 함수 변경은 메모리 복사본/patch로만 주입하며 추적 파일과 캐시를 수정하지 않는다. 결과 JSON은 코드가 있는 임시 디렉터리에 저장한다.

<!-- review-probes-code -->
```python
"""In-memory review probes; never writes project or cache files."""
from pathlib import Path
import sys,json,copy,io,unittest
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(sys.argv[1]).resolve();sys.path[:0]=[str(ROOT),str(ROOT/'eval'),str(ROOT/'tests')]
from dart_review import accounts
from dart_review.cache import ResponseCache
from dart_review.client import DartClient,NotCached
from dart_review.review import review_change
from dart_review.periods import instant,quarter,year_to_date,Period
from dart_review.compare import compare,find_restatements
from dart_review.facts import fact_from_response
from test_rules import fact,row
import build_gold

def forbidden_key():raise AssertionError('Key access forbidden')
client=DartClient(ResponseCache(ROOT/'cache'),key_loader=forbidden_key,offline=True)
outputs={}
class MissingBridge:
    def __init__(self,mode):self.mode=mode
    def financial_statements(self,corp,year,report,basis):
        r=client.financial_statements(corp,year,report,basis)
        if (year,report)==(2024,'11011'):
            if self.mode=='missing':raise NotCached('Synthetic unavailable bridge')
            if self.mode=='013':return replace(r,status='013',body=b'{"status":"013","list":[]}')
            if self.mode=='empty':return replace(r,body=b'{"status":"000","list":[]}')
        return r
for mode in ('normal','missing','013','empty'):
    r=review_change(client if mode=='normal' else MissingBridge(mode),'00413046','OFS','total_liabilities',instant(2025,9),instant(2024,9))
    outputs['bridge_'+mode]={'status':r.status,'change':r.change,'pct':str(r.change_pct),'reasons':r.reasons,'notes':r.notes}

spec=json.loads(build_gold.SPEC.read_text())
q=copy.deepcopy(next(q for q in spec['questions'] if q['id']=='dev08'))
# Invalid restatement evidence: two different periods, same cells as the main comparison.
q['expected']['evidence']['restated_pair']=[copy.deepcopy(q['expected']['evidence'][k]) for k in ('current','base')]
g=build_gold.build_question(client,q)
outputs['wrong_restated_pair']={'pair':[{k:c[k] for k in ('year','report_code','column','amount')} for c in g['restated_pair']],
                              'cross_check_problems':build_gold.cross_check(client,q,g)}
original_label=Period.label
with patch.object(Period,'label',lambda self: original_label(self) if self.is_instant else 'WRONG FLOW PERIOD'):
    document,problems=build_gold.build(client,spec)
outputs['shared_period_label']={'example':document['answers'][0]['current_period'],'build_problems':problems}

current=fact(120,rcept='20251114000001');base=fact(100,quarter(2024,9),rcept='20241114000001')
old=fact(90,instant(2023,12),rcept='20231001000001');later=fact(95,instant(2023,12),rcept='20260317000001')
r=compare(current,base,find_restatements([old,later]))
outputs['out_of_interval_restatement']={'status':r.status,'comparison_receipts':[base.rcept_no,current.rcept_no],'change_receipts':[old.rcept_no,later.rcept_no],'reasons':r.reasons}
r=compare(replace(current,currency=None),replace(base,currency=None))
outputs['currency_missing']={'status':r.status,'change':r.change,'pct':str(r.change_pct),'currency':[None,None]}

# A same-statement breakdown is ignored in production, but no existing test kills this mutation.
rr=[row('IS','ifrs-full_Revenue','매출액',detail='가상 부문 [member]',thstrm='99')]
outputs['breakdown_normal']=accounts.resolve_account(rr,'revenue').method
with patch.object(accounts,'_is_total_row',lambda r:True):
    outputs['breakdown_mutated']=accounts.resolve_account(rr,'revenue').method
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
    outputs['mutation_ignores_detail']={'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)}

# ID-name semantic conflict. Demonstrates an unguarded risk, not a corruption seen in current cache.
r=accounts.resolve_account([row('IS','ifrs-full_ProfitLossAttributableToOwnersOfParent','당기순이익',thstrm='99')],'net_income')
outputs['conflicting_standard_id_name']={'method':r.method,'id':r.row['account_id'],'notes':r.notes}
outputs['network_requests']=client.network_requests
out=Path(__file__).with_name('probe_results.json');out.write_text(json.dumps(outputs,ensure_ascii=False,indent=2))
print(json.dumps(outputs,ensure_ascii=False,indent=2))
```

## 부록 C. 공시목록 관찰 범위의 재현

저장소 루트에서 아래 코드를 `python3 -`로 실행하는 방식으로 카카오 목록을 확인했다. 동일 범위의 8개 보고서 × 연결/별도 16개가 일치하며, 목록의 조회 종료일은 20250430이다. 조회 범위 밖의 최신성을 검사하는 코드는 아니다.

```python
from pathlib import Path
import hashlib
import json

root = Path.cwd()
meta_path = root / "cache/list.json/923165322f64f2be96bbcacff1deb055.meta.json"
meta = json.loads(meta_path.read_text())
assert meta["params"]["corp_code"] == "00258801"
raw = meta_path.with_name(meta_path.name.replace(".meta.json", ".body")).read_bytes()
assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
listing = json.loads(raw)
index = {}
for path in (root / "cache/fnlttSinglAcntAll.json").glob("*.meta.json"):
    item = json.loads(path.read_text())
    params = item["params"]
    if params["corp_code"] == "00258801":
        index[(int(params["bsns_year"]), params["reprt_code"], params["fs_div"])] = path
passed = 0
for year in (2023, 2024):
    for code, month in (("11013", "03"), ("11012", "06"), ("11014", "09"), ("11011", "12")):
        latest = max((r for r in listing["list"] if f"({year}.{month})" in r["report_nm"]), key=lambda r: r["rcept_no"])
        for basis in ("CFS", "OFS"):
            path = index[year, code, basis]
            data = json.loads(path.with_name(path.name.replace(".meta.json", ".body")).read_text())
            passed += {r["rcept_no"] for r in data["list"]} == {latest["rcept_no"]}
print("matched", passed, "/ 16; listing end", meta["params"]["end_de"])
# matched 16 / 16; listing end 20250430
```
