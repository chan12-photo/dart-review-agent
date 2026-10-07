# 1-5 실행 전 독립 검토 결과: 평가 실행기와 채점 규칙

- 작성: 2026-10-07, Codex.
- (Claude 주: 저장소 공개에 대비해 로컬 절대 경로만 `<저장소>`, `<임시 폴더>`로 바꿨다. 그 밖의 내용은 바꾸지 않았다.)
- 요청: `docs/reviews/1-5_codex_request.ko.md`의 1~6번과 1-3 반영분 재확인.
- **최종 검토 기준 커밋: `8c19b8208a6ba17ef2f9845a6328dbf6abc579f1`.**
- 중단 전 검토는 `7a8443d` 기준이었다. 이어서 작업할 때 `8c19b82`의 수정과 `1-5_codex_partial.ko.md`를 발견해, 이전 프로브를 새 코드에 다시 적용했다. 아래 미해결 발견은 재개 후에도 재현된 것만 적었다.
- 추적 파일을 수정하지 않았다. 인증키 파일, 봉인된 회사의 데이터, OpenDART API, 실제 Ollama에 접근하지 않았다. HTTP 검증은 가짜 opener로 전송 경계를 관찰했다.

## 0. 판단

**프로젝트를 계속할 근거는 있다. 다만 현재 채점기의 점수로 1-5의 진행·전환을 판정하면 안 된다. 평가 실행기와 채점 기준을 먼저 보완해야 한다.**

재무 규칙의 이전 지적 R1~R5는 재현한 범위에서 막혔고, 현재 규칙만 실행은 13/13이다. 반면 평가기에서는 다음이 남아 있다.

1. 모델의 잘못된 인자가 평가 전체를 중단시키고, 앞서 완료한 문항까지 저장되지 않는다.
2. 모델이 만들어 낸 숫자를 도구 오류 문구로 한 번 돌려받으면 금융 근거로 인정한다.
3. 구조화 칸이 맞으면 사용자에게 보이는 문장의 기간·증감·이유가 틀려도 통과한다.
4. 실제 반올림이나 버림으로 나오지 않는 숫자까지 허용한다.
5. 실패한 생성 요청을 0회로 기록하고, 요청별 실제 payload와 원시 응답이 남지 않는다.

이는 **현재 모델이 못한다는 결과가 아니다. 모델을 평가하는 장치의 문제**다. 실제 모델은 이번 검토에서 한 번도 실행하지 않았다. 전면 재작성이나 새 모델 도입을 권하지 않는다. 8절의 필수 보완을 끝내고 기준을 고정한 뒤, 계획된 작은 평가를 한 번 실행하는 순서가 적절하다.

## 1. 직접 실행한 검증과 이미 해결된 항목

### 1.1 최신 커밋에서 실행한 명령

작업 위치: `<저장소>`

| 명령 | 결과 | 이 결과가 의미하는 범위 |
|---|---|---|
| `python3 -m unittest discover -s tests` | **139개 통과**, 0.825초 | 기존 테스트가 현재 코드에서 통과한다. 아래 반례를 모두 검사한다는 뜻은 아니다 |
| `python3 eval/build_gold.py --check` | **13개 정답 일치**, 파일 최신 | 정답 생성과 규칙 구현의 현재 대조 결과 |
| `python3 scripts/check_trap_tests.py` | 기본 규칙 테스트 **58개 통과**, 변이 **10/10개 검출** | 준비된 10종 규칙 결함을 테스트가 감지한다 |
| `python3 eval/run_eval.py --mode rules --out <새 임시 경로>/rules` | **13/13**, 숫자 10/10, 기준 12/12, 거절·되묻기 3/3, 근거 없는 숫자 0 | 올바른 해석을 미리 넣은 규칙·템플릿·채점기의 통합 결과. 자연어 해석이나 모델 성능이 아니다 |
| 부록의 가짜 답·가짜 모델·가짜 HTTP 프로브 | 아래 발견 재현 | 실제 모델이 이런 답을 했다는 기록이 아니다 |

단위 테스트 출력의 argparse 오류 문구는 잘못된 실행 인자와 기존 출력 경로를 거부하는 테스트의 예상 출력이다. 테스트 실패가 아니다. 규칙만 실행의 모델 요청·모델 도구 호출 0회, 지연 시간 0은 해당 집계 방식의 결과이며 실제 Python 실행 시간이 0이라는 뜻이 아니다.

### 1.2 중단 중 반영된 수정 재검증

| 항목 | `7a8443d`의 재현 | `8c19b82`에서 같은 입력 | 판단 |
|---|---|---|---|
| dev01의 `32735035000000원` | 접수번호로 오인해 탈락 | `passed=true`, 근거 없는 숫자 없음 | 해당 오탐 해결 |
| 변화율 10.88%를 `10.88배`로 표기 | 통과 | 근거 없는 배수로 탈락 | 해당 미탐 해결 |
| 변화율 6.58%를 `6.6%p`로 표기 | 통과 | 근거 없는 퍼센트포인트로 탈락 | 해당 미탐 해결 |
| dev02의 한 시점 값에만 잘못된 `start` 입력 | None·문자열 정렬 TypeError | 예외 없이 기준·숫자 오류로 탈락 | 해당 중단 해결 |
| `function`이 문자열/None인 도구 호출 | 객체라고 가정해 예외 가능 | 추가된 회귀 테스트 통과 | 해당 모양 처리 해결. 이름·인자의 다른 타입 오류는 E1 참고 |

14자리 처리와 비율 종류 분리는 수정 효과가 확인됐다. 그러나 숫자의 의미를 구분하는 전체 문제가 해결된 것은 아니다(E2~E5). 무작위로 **형식이 맞는** 답을 생성하는 테스트는 유용하지만, 잘못된 타입이 들어오는 경계 검증을 대신하지 않는다.

## 2. 발견 사항

아래 `E` 번호는 이번 감사의 번호이며 이전 감사 `R1~R5`와 다르다. 심각도는 평가 결과에 미치는 영향을 기준으로 했다. 개별 반례는 가짜 답이므로 실제 발생 빈도는 확인하지 못했다.

### E1. 잘못된 타입이 평가 전체를 중단시키고 완료 기록도 사라짐

- **심각도: 중요 — 1-5 실행 전 필수 수정.**
- 위치: `dart_review/answer.py:117`, `dart_review/tools.py:82`, `:86`, `:92`, `:120`, `:158`; `eval/run_eval.py:162`, `:190`, `:215`.
- 근거:
  - 최종 답의 `account=[]` → `AnswerFormatError`가 아니라 **TypeError**.
  - 도구 인자의 `account=[]`, `basis=[]`, `current_period.kind=[]` → **TypeError**.
  - `current_period.month=12.0` → 값 비교를 통과한 뒤 날짜 생성에서 **TypeError**.
  - 가짜 oracle 실행에서 dev01 정상 응답 후 dev02의 `account=[]` 응답을 넣었다. 가짜 생성 요청 **2회** 뒤 중단됐고, 지정한 출력 디렉터리는 **존재하지 않았다**. 완료한 dev01도 저장되지 않았다.
- 원인: 사전 타입 검사 없이 dict membership을 사용하고, 실행기는 `ModelError`만 문항 단위로 처리한다. 출력은 전체 문항 실행이 반환된 후에야 생성한다.
- 제안:
  1. 도구 이름·계정·기준·기간 종류의 문자열 여부와 month의 정수 여부부터 검증한다. 잘못된 모델 입력은 계약 오류로 기록한다.
  2. 응답 파싱·채점의 예상 오류가 다른 문항을 지우지 않도록 격리한다. 내부 버그는 모델 오답과 구분해 `evaluator_error` 등으로 남긴다.
  3. 실행 메타데이터는 시작 시, 요청 기록은 요청별, 문항 결과는 완료 즉시 저장한다. 중단돼도 완료분을 읽을 수 있어야 한다.
  4. 새 경로 생성과 기존 경로 거부는 유지한다. 예외를 모두 숨기고 평가를 성공으로 끝내는 방식으로 고치지 않는다.

수정된 시점 정렬 사례는 이제 중단시키지 않는다. 현재의 저장 손실 재현에는 별도의 `account=[]` 입력을 사용했다. 스키마 강제가 이 입력을 항상 막는지는 실제 런타임에서 검증하지 않았으며, 특히 도구 인자에 대한 Python 검증은 독립적으로 필요하다.

### E2. 도구 오류가 모델이 지어낸 숫자의 근거로 사용됨

- **심각도: 중요 — 1-5 실행 전 필수 수정.**
- 위치: `dart_review/tools.py:158`, `eval/run_eval.py:151`, `eval/scoring.py:123`, `dart_review/numbers.py:185`.
- 가짜 전체 흐름 재현:
  1. 정상 dev01 `compare_values` 호출과, 존재하지 않는 `unknown_영업이익률99.9%` 호출을 반환.
  2. 서버가 `알 수 없는 도구: unknown_영업이익률99.9%` 오류를 반환.
  3. 구조화 칸은 정상 dev01 값으로 유지하고 문장에 **“영업이익률은 99.9%입니다.”** 추가.
  4. 결과: **`passed=true`, `ungrounded=[]`, `warnings=[]`**. 가짜 모델 요청 3회, 도구 호출 2회.
- 원인: `seen`의 모든 JSON 문자열을 숫자 허용 집합으로 수집한다. 오류 문구 속 모델 입력도 재무 근거가 된다. `%/배/%p` 분리 후에도 재현됐다.
- 제안: 도구 실행 기록과 금융 근거의 집합을 분리한다. 성공한 도구가 검증해 반환한 금액·변화량·변화율·식별 정보 등만 종류별로 수집하고, 오류·인자 반향·원시 모델 문장을 금융 근거로 승격하지 않는다. 필요한 재작성 메모의 수치는 출처가 확인되는 별도 구조로 보존할 수 있다.
- 계약 문제: `EVAL_DESIGN` 4절은 “모델이 본 JSON의 모든 숫자와 질문 숫자”를 허용한다. 이 문구를 그대로 구현해도 SCOPE의 “숫자가 재무 도구 근거로 추적된다”는 보장을 충족하지 못한다. 질문 속 추측 숫자를 인용하는 것과 사실로 확정하는 것도 구별해야 한다. 현재 고정 13문항에 질문 속 임의 금액 반례가 있는 것은 아니다.

### E3. 구조화 칸이 맞으면 사용자에게 보이는 틀린 설명이 통과

- **심각도: 중요 — 1-5 진행 판정에 반영할 기준을 실행 전에 확정해야 함.**
- 위치: `eval/scoring.py:89`, `:109`, `:117`, `:123`, `:129`; `docs/EVAL_DESIGN.ko.md:55`, `:104`; `docs/GOLD_RULES.ko.md` 2~3절.
- 방법: 실제 캐시의 올바른 도구 결과와 구조화 칸은 그대로 두고 `answer` 문장만 잘못 작성했다. **13문항 각각에서 잘못된 사용자 문장이 통과하는 반례를 만들었다.** 목록은 3절에 있다.
- 대표 사례:
  - dev01: 2025·2024 매출을 서로 바꾸고 “10.88% 감소”라고 써도 통과.
  - dev03: 1~9월 현금흐름을 “7~9월 3개월”로 설명해도 통과.
  - dev09: **“흑자 전환하지 않았고 계속 적자입니다.”**가 `흑자 전환` 부분 문자열을 포함해서 통과.
  - dev10: 비교 거절 이유를 **“서버 장애”**로 바꿔도 통과.
  - dev12: 실제 금액을 문장에 내놓고, 별도 `clarifying_question`에 두 후보를 쓰면 통과.
- 구별할 점: dev05의 원인 단정과 dev08의 과도한 확정은 이미 알려진 수동 검토 항목이다. 이번 발견은 그 두 문항 외에도 기간·증감·데이터 없음 사유·되묻기 실행이 같은 방식으로 빠진다는 것이다.
- 제안:
  - 13문항 전체에 대해 **본문의 회사·계정·기준·기간·증감·거절 이유·근거 없는 단정**을 사람이 확인할 표를 모델 실행 전에 고정한다.
  - `automatic_passed`와 `human_reviewed_passed`를 분리하고, 가능성 판정은 어떤 점수를 쓰는지 먼저 적는다. 자동 점수 원본은 보존한다.
  - 자동화가 꼭 필요하면 수치·기간 문장은 검증된 구조에서 생성하는 작은 출력 방식을 검토할 수 있다. 새로운 LLM 심판을 추가할 필요는 없다.
  - dev12는 회사와 계정 범위, 설명 본문에서의 확정 금액 제시도 점검한다.

현재 `passed`는 구조와 숫자 집합에 관한 자동 통과다. 사용자에게 보이는 답까지 “엄격한 정답”이라고 표현하기에는 범위가 좁다.

### E4. 허용 오차가 반올림·버림보다 넓어 잘못 올린 금액도 통과

- **심각도: 중요 — 1-5 실행 전에 정책·구현을 함께 정리.**
- 위치: `dart_review/numbers.py:169`, `docs/EVAL_DESIGN.ko.md:68`.
- 근거:

| 실제 허용 근거 | 가짜 표기 | 현재 결과 | 실제 반올림/버림과의 차이 |
|---|---|---|---|
| 1.24조 | `1.3조` | 근거 있음 | 0.1조 자리의 반올림·버림은 모두 1.2조 |
| 327,543,643,155원 | `약 3,276억 원` | 근거 있음 | 1억 자리의 반올림·버림은 모두 3,275억 |
| 10.81% | `10.9%` | 근거 있음 | 소수 첫째 자리의 반올림·버림은 모두 10.8% |
| dev08의 3,275,436,431,552원 | `약 4조 원` | 문항까지 통과 | 1조 자리의 반올림·버림은 모두 3조 |

- 원인: `abs(표시값 - 허용값) < 표시단위`는 위·아래를 모두 넓게 허용한다. 코드가 문서의 “표시단위 안”이라는 수식을 어긴 것은 아니다. **그 수식이 ‘반올림과 버림을 인정’이라는 의도보다 넓은 설계 문제**다.
- 제안: 표시단위로 실제 근거를 반올림한 값 또는 버린 값과 같은지 비교한다. 허용 자릿수나 최소 정보량 제한이 필요하다면 지금 확정한다. 부호·증감 의미는 E3의 별도 검토 대상이다.
- 정상 사례도 확인했다: 1.19조 → 1.1조는 유효한 버림, 327,560,000,000원 → 약 3,276억은 유효한 반올림, 3.275436…조 → 3.3조는 유효한 반올림이다. 이들을 오답으로 분류하면 안 된다.

### E5. 미지원 금액 일부를 조용히 버리고 날짜·14자리 숫자의 역할을 혼동

- **심각도: 중요 — 잘못된 통과는 수정, 표기 오탐은 사전 지정한 수동 정정 절차로도 처리 가능.**
- 위치: `dart_review/numbers.py:75`, `:84`, `:155`, `:177`, `:179`; `docs/EVAL_DESIGN.ko.md:105`.
- 근거:
  - 실제 근거가 1.02조일 때 **`1조 9백억 원`**에서 추출되는 것은 `1조`뿐이다. `9백억`은 `unparsed`로도 남지 않고, 남은 `1조`는 근거 있음으로 판정한다. `1조 2백억 원`도 같은 방식이다. “모르는 표기는 보수적으로 판정 불가 숫자로 센다”는 문서와 다르다.
  - 실제 도구에 있는 접수번호 `20260310002820`을 **“이번 매출액은 20260310002820원입니다.”**라고 써도 dev01이 통과한다. 14자리 금액 오탐 수정은 맞지만, 명시적인 `원` 단위까지 접수번호 허용으로 처리한다.
  - 실제 날짜 2025-09-30을 `20250930`으로 쓰면 금액으로 해석해 근거 없음, `2025.09.30`은 일부가 판정 불가다. 반면 `2025/09/30`은 연도만 확인하며 월·일은 검사에서 빠진다.
  - `2025-02-31`은 월 1~12·일 1~31 범위 검사로 통과한다. 실제 기간이 9월 말인데 본문에 6월 말이라고 쓰는 경우도 구조화 날짜가 맞으면 통과한다.
- 제안:
  1. 인식하지 못한 규모 단위를 작은 개수 표현으로 버리지 말고 해당 숫자 범위를 `unparsed`로 남긴다.
  2. `원`이 붙은 숫자는 금액으로 검증하고, 접수번호라는 이유로 허용하지 않는다.
  3. 지원 날짜 표기를 명시한다. 흔한 표기를 늘리거나, 평가 전 고정한 수동 검토에서 표기만의 오탐을 정정하되 원점수와 정정 이유를 함께 남긴다.
  4. 유효한 달력 날짜인지와 질문이 요구한 날짜인지는 별개다. 본문의 실제 기간 일치는 E3에서 확인한다.

전문적인 한국어 숫자 파서를 전부 만들고 나서 평가하자는 제안은 아니다. 현재 확인한 누락·종류 혼동과 명시적인 수동 검토 범위를 먼저 정하자는 것이다.

### E6. 실제 요청 시도·payload·응답 기록이 계약에 못 미침

- **심각도: 중요 — 1-5 실행 전 필수 수정.**
- 위치: `eval/run_eval.py:113`, `:130`, `:160`, `:219`; `dart_review/llm.py:68`, `:117`, `:125`, `:133`; `docs/EVAL_DESIGN.ko.md:93`.
- 가짜 HTTP 전송 경계에서 확인한 것:
  - 연결 오류를 발생시키면 adapter의 실제 생성 시도는 **1**, 전송 경계 도달도 **1**인데 문항 기록의 `model_requests`는 **0**, 응답 0, 지연 0이다. 카운터를 성공 반환 이후에 올린다.
  - 정상 가짜 전체 흐름의 각 요청 역할은 `[system,user]`, `[system,user,assistant,tool]`, `[system,user,assistant,tool,assistant,user]`였다. 저장되는 것은 마지막 대화 하나와 가공된 reply 목록이다.
  - **전송 payload 자체는 깊은 복사되어 있었다.** 이후 `messages`를 바꾸어도 첫 전송 객체는 변하지 않았다. 이전 AI Job Agent에서 문제였던 mutable payload 저장 버그와 혼동하지 않았다.
  - 그러나 요청별 `tools`/`format`/옵션을 포함한 실제 payload와 원시 서버 응답을 저장하지 않는다. `done`, `created_at`, 서버가 반환한 모델 이름, 원래 tool_calls의 비정상 원소 등은 사라진다.
  - 모델 이름·digest·런타임·설정은 실행 메타데이터에 한 번 저장한다. 문서의 “요청마다 기록”은 현재와 다르다. 고정된 실행 ID로 연결하는 설계도 가능하지만 그렇게 명시해야 한다.
- 제안: 전송 함수 경계에서 요청 스냅샷/전송 바이트 해시, 원시 응답, 예외, 시도 수·응답 수, 각 소요시간을 별도로 보존한다. 시간 초과·HTTP 오류·불완전 응답도 시도에 포함한다. 측정되지 않은 값은 null로 둔다. 모델 지연과 전체 문항 실행 시간도 구별한다.
- 추가 경계 문제: 가짜 서버의 `tool_calls=[42]`를 adapter가 `[]`로 조용히 바꾼다. 형식 오류를 “모델이 도구를 부르지 않았다”로 바꾸지 말고 원시 응답과 구조 오류를 보존해야 한다.

### E7. 진단 지표의 분모와 “첫 도구 호출” 정의가 문서와 다름

- **심각도: 중요 — 1-5 실행 전 수정 또는 지표 이름·분모를 명시.**
- 위치: `eval/scoring.py:75`, `:148`; `eval/run_eval.py:149`; `docs/EVAL_DESIGN.ko.md:82`, `:86`.
- 근거:
  - dev01 정상 + dev02 형식 오류를 집계하면 전체 통과는 **1/2**인데 숫자 정확도·기준 정확도는 **1/1**이다. 형식 오류에서 해당 필드가 None으로 남아 분모에서 제외된다.
  - 규칙만 실행의 기준 정확도는 **12/12**로, 숫자 문항 10개 외에 거절 문항 2개도 포함한다. 문서는 “숫자 문항”으로 적었다.
  - 첫 도구 호출의 basis를 INVALID로 만들고, 다음 호출에서 바로잡으면 `tool_args_ok=true`가 된다. 현재 코드는 첫 호출이 아니라 **첫 실행 성공 호출**을 검사한다. 가짜 흐름은 4회 요청·2회 도구 호출 후 통과했다.
- 제안: 문항의 평가 적용 여부는 정답에서 먼저 정하고, 형식 실패는 해당 지표 실패로 포함하거나 조건부 정확도와 적용/채점 가능 건수를 병기한다. 첫 도구의 인자 정확도와 오류 후 복구 성공을 분리한다.
- 해석 제한: 전체 `passed` 분모는 형식 오류를 포함하고 있었다. 위 문제를 근거로 전체 통과율 분모까지 부풀려졌다고 주장하지 않는다. 원인 분석에 쓰는 하위 지표가 왜곡된다.

### E8. 도구 예산을 넘긴 묶음에서 미응답 tool call을 둔 채 최종 요청 전송

- **심각도: 중요 — 1-5 실행 전 오류 종료 경로 정리.**
- 위치: `eval/run_eval.py:140`, `:143`, `:159`.
- 근거: 한 assistant 응답에 도구 호출 4개를 넣으면 3개 실행 후 `budget_exceeded=true`가 되지만, **assistant의 호출은 4개, tool 응답은 3개인 메시지**로 최종 schema 요청을 또 보낸다. 가짜 모델 기준 생성 요청 2회, 도구 실행 3회, 문항 실패다.
- 이미 맞는 부분: 도구를 4개 실행하지 않았고, 최종 점수도 예산 초과로 실패였다.
- 남는 문제: 짝이 없는 호출이 서버의 메시지 오류를 유발하면 예산 초과와 연결 형식 오류가 섞인다. 실제 Ollama가 이 메시지를 어떻게 처리하는지는 이번에 호출하지 않아 확인하지 못했다.
- 제안: 예산 초과를 기록하고 최종 생성 없이 종료하는 단순한 경로가 적절하다. 계속 요청할 설계라면 실행하지 않은 호출의 상태와 완결된 메시지 대응을 명확히 해야 한다.

### E9. 연결·별도 나란히 도구가 통화 검증을 우회

- **심각도: 중요 — 현재 고정 13문항 평가 후로 미룰 수 있으나 제품 출력에 재사용하기 전 수정.**
- 위치: `dart_review/tools.py:131`, `:146`.
- 근거: 실제 dev05 캐시 응답을 메모리에서 복사해 OFS 행의 통화만 USD로 바꿨다. 결과는 통화 `['KRW','USD']`, 상태 `나란히 표시`, 차이 **95,562,929,000,000**, 설명 **“같은 통화의 집계 범위 차이”**였다. 내부 `compare()`의 상태는 `비교 불가`였으나 wrapper가 그 이유를 사용하지 않는다.
- 제안: 연결·별도라는 기준 차이만 특별히 허용하되, 같은 회사·계정·기간·통화·행 확정 여부는 차액 계산 전에 확인한다. 부적절하면 두 원문 값만 단위를 구분해 표시하고 차액은 내놓지 않는다.
- 범위: **현재 dev05의 실제 캐시는 양쪽 모두 KRW**다. 이 반례 때문에 저장된 dev05 정답을 틀렸다고 고치면 안 된다. 과거 R5의 `compare()` 수정 자체는 작동했다. 새 도구 wrapper의 누락이다.

### E10. 계약 문서·스키마·서버 검증 사이의 작은 불일치

- **심각도: 사소 — 모델 실행 전에 문서·명시 규격을 맞추는 편이 좋음.**
- 위치: `docs/EVAL_DESIGN.ko.md:30`, `dart_review/answer.py:24`, `:30`, `:117`, `:134`; `dart_review/tools.py:27`, `:51`, `:79`.
- 근거:
  - 문서는 `values[].period.start/end`처럼 읽히지만 실제 답 스키마와 프롬프트는 `values[].start/end`이다. 문서대로 중첩 period를 넣은 가짜 답은 형식 오류였다. 실제 모델이 받는 프롬프트는 평평한 구조로 일치한다.
  - 도구 스키마는 추가 필드를 금지하지 않지만 서버는 정확한 필드 집합만 허용한다. year 허용 범위도 서버에만 있다.
  - 최종 답 스키마의 account는 임의 문자열, change_pct도 임의 문자열이나 서버는 지정 계정 키와 소수 둘째 자리 형식을 요구한다.
- 제안: 문서를 실제 구조로 수정하고, 지원되는 범위에서 스키마 제약을 서버와 일치시킨다. 스키마 출력이 성공했다고 서버 계약까지 통과했다고 표현하지 않는다.

## 3. 13문항별 공정성 확인

아래는 **각 문항의 정상 구조화 필드와 실제 도구 근거를 고정하고, 사용자 본문을 바꾼** 검사다. 정답을 바꾸거나 실제 모델을 다시 돌린 결과가 아니다.

| 문항 | 통과한 틀린 본문 예 | 놓치는 판단 |
|---|---|---|
| dev01 | `2025년 매출은 300.9조 원, 2024년은 333.6조 원으로 전년보다 10.88% 감소` | 두 연도의 대응과 증가/감소 |
| dev02 | `2025년 6월 30일 자산총계는 523.7조 원` | 실제 요청은 9월 말 |
| dev03 | `2025년 7~9월 3개월 영업활동현금흐름은 56.5조 원` | 실제 근거는 1~9월 누적 |
| dev04 | `2025년 7~9월 3개월 영업이익은 6,933억 원` | 누적을 단독 분기로 설명 |
| dev05 | `연결과 별도 차이 95.6조 원은 모두 자회사 매출 때문` | 원인 단정. 현재 warnings도 비어 있음 |
| dev06 | `2023년 3분기 누적 매출은 2.16조 원` | 실제 3개월 값을 누적으로 설명 |
| dev07 | `전기 영업이익은 앞 보고서와 전혀 달라지지 않았습니다` | 앞 보고서와 다른 값을 부정 |
| dev08 | `2024년 3분기말 부채총계의 회계 기준이 실제로 바뀐 것이 확실` | 관찰 범위를 넘어선 확정 |
| dev09 | `흑자 전환하지 않았고 계속 적자` | 부정문 속 키워드를 정답으로 인정 |
| dev10 | `서버 장애라 비교할 수 없습니다` | 미지원 비교 조건과 장애 혼동 |
| dev11 | `삼성전자라는 회사가 존재하지 않아 자료가 없습니다` | 미제공 연도와 회사 부재 혼동 |
| dev12 | `영업이익으로 확정해서 답하겠습니다` | 본문에서는 확정하면서 별도 필드로만 되묻기 |
| dev13 | `연결 기준 2025년 2분기 3개월 영업이익은 2,660,105,000,000원` | 실제는 별도 상반기 누적 |

dev13의 처음 만든 `6,211억` 반례는 근거 없는 숫자로 정상 탈락했다. 이를 숨기지 않았으며 원시 프로브에 보존했다. 위 표의 dev13은 별도 반례로 실제 금액을 사용하고 기준·기간만 틀리게 적은 것이다. 또 dev01·04·07·08·10·11은 본문을 단순히 `확인했습니다.`로 바꿔도 통과했다.

### 특별히 요청된 판정에 대한 의견

| 결정 | 의견 | 이유/최소 보완 |
|---|---|---|
| dev05 `나란히 표시`, change/change_pct=null | **동의** | 시간 변화와 집계 범위 차이를 나누는 계약이다. 올바른 차액은 문장으로 허용되고 정상 답은 통과했다. change에 차액을 넣으면 의도대로 탈락한다. 원인 단정은 별도 사람 검토 필요 |
| dev08 과도한 단정은 사람이 확인 | **조건부 동의** | 완전한 의미 자동 판정을 당장 만들 필요는 없다. 그러나 “틀린 답”이라는 GOLD_RULES/이전 반영 내역과 연결해 최종 판정에 반영해야 한다. 자동 점수 옆 주석만으로 끝내지 말 것 |
| dev10 대안 제시 비채점 | **동의** | “가능하면” 제시하는 부가 품질로 둘 수 있다. 다만 거절 이유의 정확성은 핵심이며 서버 장애라고 설명하는 것을 정답으로 두어서는 안 된다 |
| dev12 두 후보 이름 필수 | **조건부 동의** | 두 개념을 구별하는 것은 타당하다. `영업이익과 순이익 중…`은 GOLD_RULES상 동의어인데 현재는 탈락한다. 계정별 승인된 동의어로 판정하고 본문 금액·확정 답변도 확인할 것 |
| 시점 값 `start=null` | **동의** | 내부 표현으로 일관적이고 프롬프트에 명시됐다. 끝 날짜와 같은 start를 쓰는 답은 계약 위반으로 처리할 수 있다. 부분 오류가 채점기를 중단시키던 결함은 해결됐다 |

dev12에서 company를 카카오, account를 revenue로 바꾼 답도 통과했다. 이 분기는 회사·계정 검사가 빠져 있다. 두 후보 명칭만 포함하는 것으로 공정한 되묻기 평가가 완성되지는 않는다.

## 4. 설계와 코드의 일치 요약

| 계약 항목 | 확인 결과 |
|---|---|
| 구조화 상태·결정·원 단위 금액·변화량·변화율 | 정상 사례와 의도적인 값 변경은 대체로 계약대로. 구조와 본문 의미의 일치는 별도 누락(E3) |
| dev05 change=null, 시점 start=null | 구현됨. 시점 혼합 오류도 이제 예외 없이 실패 |
| 근거는 모델이 본 결과에서만 | 정답 JSON을 직접 허용 집합에 넣지는 않음. 하지만 결과 내 오류/인자 반향도 근거로 삼는 계약 자체가 부적절(E2) |
| 반올림·버림 | “표시단위 미만 차이” 수식은 구현됨. 의도한 반올림·버림보다 넓음(E4) |
| 배수·%p와 변화율 구분 | 최신 커밋에서 수정되고 재현 확인 |
| 미지원 숫자 보수적 처리 | 일부 표기는 아예 누락되어 미구현(E5) |
| 되묻기에는 숫자를 내놓지 않음 | 구조화 칸만 검사. 실제 본문 금액은 허용 근거에 있으면 통과(E3) |
| 첫 도구 호출 인자 정확도 | 첫 성공 호출을 세는 불일치(E7) |
| 숫자/기준 지표의 적용 문항 | 형식 실패가 분모에서 빠지고 기준에는 거절 문항도 포함(E7) |
| 요청마다 모델·설정·응답 기록 | 전역 identity와 가공 reply만 보존. 실제 요청별 기록이 부족(E6) |
| 예산 초과 시 실패 | 최종 점수는 실패. 다만 미응답 호출 상태로 마지막 생성 요청을 보냄(E8) |

## 5. 세 가지 평가 방식과 프롬프트·설정

### 5.1 ②에 원본 행 대신 도구 결과를 주는 선택

**현재 제품 역할 분담에는 타당하다.** 칸의 기간 해석·계산·비교 가능성은 Python이 맡고 모델은 그 결과를 전달한다. ②는 이 계약 안에서 “올바른 도구 결과를 받은 모델의 답 작성”을 잰다. 원본 행에서 스스로 재무 의미를 찾는 능력으로 표현하면 안 된다.

다만 ②와 ③의 점수 차이를 곧바로 “질문 해석·도구 사용의 순수한 손실”이라고 계산하는 것은 과도하다.

- ②는 정답 해석으로 고른 결과를 한 번에 받고 최종 schema 응답 1회를 만든다.
- ③은 도구 대화, 오류·추가 결과, 예산, 중간 assistant 설명을 거쳐 별도 최종 schema 요청을 만든다.
- 따라서 문맥 길이·오류 회복·답 작성 경로도 다르다. 차이는 **도구 사용을 포함한 전체 흐름의 추가 어려움**으로 보고, 문항별 실제 도구 인자로 원인을 나누는 편이 정확하다.
- ②가 낮을 때도 현재처럼 채점/연결 문제가 남아 있으면 모델 자체의 한계로 바로 결론내릴 수 없다.

### 5.2 dev12에 두 후보의 결과를 모두 제공

조건부로 공정하다. “근거가 있어도 모호한 질문을 임의로 확정하지 않는가”를 평가하는 구성이다. 다만 후보 두 개를 직접 제공하므로 **스스로 모호성을 발견하고 후보를 찾는 능력**을 측정하지는 않는다. 결과 표에서 이 차이를 밝혀야 한다. 실제 금액을 먼저 답하고 뒤에서 되묻는 답을 막는 E3 보완도 필요하다.

### 5.3 ①은 규칙 기반 자연어 기준선이 아님

`interpretation_calls()`는 질문의 `expected`를 읽는다. 질문 문장에서 회사·계정·기간을 추출하는 코드가 아니다. ①의 13/13은 유용한 통합 검사지만 SCOPE 7절·ROADMAP 2-2의 **자연어 규칙 기준선과 Agent의 비교**를 이미 끝냈다는 의미가 아니다. 해당 기준선은 계획대로 이후 만들 수 있다.

### 5.4 예산

문항당 모델 최대 5회·도구 최대 3회는 현재 두 개의 고수준 도구에 대해 작은 가능성 평가를 제한하는 값으로 합리적이다. 도구 내부에서 여러 보고서를 읽는 것은 모델 도구 호출 한 번과 다르므로 보고서 조회 횟수로 해석하지 않는다.

현재 정상 성공 흐름도 tool 요청 → tool 결과 후 assistant → 별도 최종 schema 응답으로 3회가 될 수 있다. 이 비용을 포함한 설계로 기록해야 한다. 자동 재시도는 adapter에 없었다. 다만 실제 시도 예산·실패 기록은 E6, 묶음 도구 초과는 E8을 먼저 고친다. 이번 감사에서 예산 확대나 Agent 루프 확장을 제안하지 않는다.

### 5.5 프롬프트 누출 여부

- `SYSTEM_PROMPT`와 `TOOL_SPECS`에 문항 ID별 정답표·기대 상태·금액 목록을 넣은 것은 발견하지 못했다.
- 연결 기본값, 상반기/분기 해석, 모호한 이익의 후보는 제품 정책이다. 이를 알려 주는 것 자체는 부당한 정답 누출이 아니다. 다만 이런 명시된 정책을 따라 하는 성능을 측정한다.
- `prompts.py:13`의 금액 표기 예 **`333.6조 원`은 dev01/dev05의 실제 연결 매출과 겹친다.** 이것만으로 평가 전체가 무효는 아니지만 불필요한 특정 수치 힌트다. 실행 전에 무관한 표기 예로 교체하거나 placeholder로 바꾸고 프롬프트 버전을 올리는 것이 낫다.
- ②가 정답 해석으로 결과를 준비하는 것은 의도한 oracle 조건이다. 이를 일반 도구 선택 성공으로 계산하지 않는다.

### 5.6 Ollama 옵션과 재현 조건

코드에 설정된 것은 `temperature=0`, `num_ctx=8192`, `num_predict=4096`, `stream=false`, `think` 미전송, `truncate=false`, `shift=false`, 요청 timeout 600초다. 실제 설치 모델·digest·버전·속도·메모리·중첩 schema 호환성은 이번 요청의 금지 범위여서 확인하지 않았다.

- 이 값들을 바꾸어 성능을 높이는 실험을 이번 감사와 섞을 이유는 없다.
- `think=None`은 생각 안 함이 아니라 **기본값 사용**이다. 요청에서 생략했다는 사실과 실제 반환된 thinking/종료 사유/토큰을 그대로 기록해야 한다.
- `truncate=false` 등을 보냈다는 사실과 실제 런타임이 컨텍스트 초과를 어떻게 처리하는지는 다르다. “몰래 잘라내지 못한다”는 보장은 코드 검사만으로 검증되지 않는다. 1-5의 연결 확인에서 확인 가능한 것만 보고할 것.
- 현재 identity, commit, 정답·질문 해시는 재현의 일부다. 요청/원시 응답 기록, 프롬프트·도구·스키마의 버전 또는 해시, 실패·중단 기록까지 보완해야 한다. dirty=true라는 표시만으로 수정된 소스를 복원할 수는 없다.
- 온도 0과 동일 캐시만으로 모델의 비트 단위 결정성을 주장하지 않는다.

13문항에서 80% 이상은 최소 **11/13(84.62%)**이다. 이 기준과 근거 없는 숫자 0건을 사용할 때는 자동 점수와 사전 합의한 사람 검토를 어느 순서로 적용할지 실행 전에 고정해야 한다. 정답을 보고 유리한 반올림 규칙·동의어·예외를 사후 추가하지 않는다.

## 6. 1-3 반영분 재확인

| 이전 항목 | 이번에 직접 확인한 것 | 판단 |
|---|---|---|
| R1 불완전한 기준 확인 | dev08에서 연간 연결 보고서를 캐시 없음/013/빈 계정 응답으로 바꿈. 모두 원인과 함께 `확인 필요` | 재현 범위에서 해결 |
| R2 잘못된 재작성 쌍/기간 공유 | 서로 다른 기간의 쌍을 넣으면 GoldError. 생산 코드의 기간 label을 바꾸면 독립 대조에서 문제 16건 검출 | 기존 결함 해결 |
| R3 합계 행 필터 테스트 | `_is_total_row`를 항상 True로 패치하면 해당 테스트 실패. 공식 변이 검사도 검출 | 기존 테스트가 더는 무의미하게 통과하지 않음 |
| R4 다른 표준ID 이름 대체 | `당기순이익` 이름과 지배주주 귀속 ID가 충돌하는 합성 행 → `account_name_conflict` 및 확인 필요 메모 | 기존 결함 해결 |
| R5 둘 다 통화 없음 | 두 Fact의 currency=None → `확인 필요`, 이유 `통화가 확인되지 않았다` | compare의 기존 결함 해결. wrapper의 별도 결함은 E9 |

R3의 직접 변이 실행은 assertion failure가 아니라 잘못된 분해행을 포함해 선택이 모호해지고 `found.row=None`에 접근하는 **테스트 오류 1건**으로 검출됐다. 변이가 통과하지 않는다는 증거는 되지만, 실패 원인을 더 선명하게 하려면 `found.row is not None`을 먼저 단언하면 좋다. 이 작은 진단 개선을 1-5의 중단 사유로 삼지는 않는다.

### 보고서 연결과 “누적 − 3개월”

- 카카오 2023년 3분기 연결 영업수익 원본 행에서 독립적으로 정수 차감을 계산했다.
  - `thstrm_add_amount − thstrm_amount` = **3,782,812,962,240원**(2023년 1~6월).
  - `frmtrm_add_amount − frmtrm_q_amount` = **3,474,017,956,597원**(2022년 1~6월).
- `probe_facts()`의 두 파생 금액과 일치했고, source도 `thstrm_add-thstrm`, `frmtrm_add-frmtrm_q`로 구분돼 있었다.
- dev06의 보고서 연결은 성립했다. 금액만 같게 하고 기간 또는 통화를 바꾼 합성 사실은 연결되지 않았다.
- `probe_facts()`는 다른 표준ID와 이름이 충돌한 값을 기준 확인에서 제외한다. 통화는 같은 값을 묶는 키에 포함되며, 비교 대상의 통화 누락은 `compare()`가 확인 필요로 처리한다. `build_gold.py`의 자체 칸-기간 표와 label 계산은 생산 `periods.py` 변경에 함께 움직이지 않았다.
- 위 검사는 이 알고리즘이 모든 재작성·회계기준 변경을 찾는다는 증명이 아니다. 같은 기간·통화·금액의 관찰된 연결이라는 정책에 맞는 제한된 확인이다. 보고서 사이 회계정책 변화가 없다는 확정으로 확대하면 안 된다.

### dev13 독립 원본 확인

`dart_review`를 import하지 않고 캐시 JSON을 직접 읽었다.

- 원본: `cache/fnlttSinglAcntAll.json/4f36c8a50dd9648681356bcc6f383c91.body`
- SHA-256: `0b70afa73bfd5d1b508224b12412c8866a0cd8c60368d15bb3cad825644c88b5`
- 삼성전자 2025 반기 별도, IS, `dart_OperatingIncomeLoss`, 합계 행, 접수번호 `20250814003156`.
- 상반기 누적: **2,660,105,000,000원**, 전년 상반기 누적: **9,229,871,000,000원**.
- 차이: **−6,569,766,000,000원**, 변화율: **−71.18%**.
- dev13 정답과 일치한다. 이번에는 기존 12문항을 다시 독립 계산하는 감사를 반복하지 않았고, 기존 감사와 최신 `build_gold --check`, 위 표적 검사를 사용했다.

## 7. 테스트가 놓친 경계

139개 테스트 통과와 아래 반례들은 모순이 아니다. 현재 테스트의 범위 밖이거나 느슨한 계약을 그대로 검증하고 있기 때문이다.

1. 숫자 테스트는 유효한 반올림/버림과 충분히 먼 오답은 확인하지만, **반올림도 버림도 아닌 바로 옆 올림값**은 빠져 있다.
2. 정답 구조화 칸과 다른 의미의 문장을 함께 넣는 검사가 부족하다. `흑자 전환`의 부정문, 본문 기간 뒤집기, 거절 원인 바꾸기를 별도로 확인해야 한다.
3. 형식이 맞는 무작위 답 500개 × 13문항은 정상 타입 범위의 강건성 검사다. account/basis/kind의 list, float month, 숫자가 든 오류 문구는 다루지 않는다.
4. 가짜 모델로 예산 숫자를 확인하는 테스트는 미응답 tool call이 남은 후속 메시지를 실제 서버처럼 거부하지 않는다. 카운터 검사 외에 메시지 대응 검사 필요.
5. `test_odd_tool_call_shapes_do_not_crash_the_runner`는 한 응답에 이상한 호출 4개를 넣지만 도구 예산 3회 때문에 네 번째는 실행 경로에 도달하지 않는다. 해당 모양까지 이 테스트가 검증했다고 세면 안 된다.
6. `ModelError` 테스트는 예외 발생은 확인하지만 “실제 HTTP 시도 1회/응답 0회”의 집계와 완료 결과 보존은 확인하지 않는다.
7. 숫자가 들어 있는 notes를 허용하는 테스트는 있다. 오류나 모델 인자 반향이 **허용돼서는 안 되는 출처**라는 반대 검사가 없다.

테스트 개수를 늘리는 것이 목표는 아니다. 이번에 재현된 결함별로 정상/실패 경계를 하나씩 고정하고, 그 결함을 다시 넣으면 실패하는지를 확인하면 된다.

## 8. 무엇을 먼저 고치고, 무엇을 미뤄도 되는가

### 1-5 실행 전 필수

1. **E1:** 모델 입력 타입 검사, 문항별 평가기 오류 구분, 중간 저장.
2. **E2:** 검증된 수치와 오류/반향 문자열의 출처 분리.
3. **E3:** 13문항 본문 검토 기준과 최종 합격 점수 정의 확정. dev12의 회사·계정·본문 숫자도 포함.
4. **E4~E5:** 반올림/버림을 실제로 적용하는 규칙, 숫자 일부 누락·접수번호를 금액으로 쓰는 우회 차단. 지원하지 않는 표기의 수동 정정 절차도 실행 전에 명시.
5. **E6~E8:** 시도/응답 카운터와 실제 요청·응답 기록, 하위 지표의 분모/첫 호출 정의, 예산 초과 종료 메시지 정리.
6. **E10 및 프롬프트:** 문서의 period 구조와 실제 규격 일치. 불필요한 `333.6조` 예 제거 여부 확정 및 버전 기록.

일부 본문 의미 검사를 수동으로 수행하는 것은 허용 가능한 최소안이다. 자동 평가기가 한국어 의미를 전부 이해할 때까지 작업을 확대할 필요는 없다. 대신 자동 통과와 사람이 확인한 정답을 반드시 따로 보존한다.

### 고정 13문항의 1-5 실행 후로 미뤄도 되는 것

- E9의 나란히 도구 통화/행 확정성 확장: 현재 dev05는 정상 KRW 자료여서 고정 평가를 막지는 않음. 실제 사용자 입력 범위를 넓히기 전 수정.
- 한국어 날짜·숫자 표기의 전면 지원: 현재 지원 범위와 수동 검토 절차를 고정한 뒤 단계적으로 확대.
- 키워드 자연어 기준선: 로드맵 2-2에서 구현. 지금의 rules 13/13으로 대체했다고 주장하지 않음.
- 재작성 연결 규칙의 더 넓은 일반화, 봉인 회사 평가, 원인 설명 RAG: 이번 가능성 평가 뒤 별도 범위.
- R3의 assertion 진단 개선 등 실패 메시지 정리.

**종료 기준:** 위 필수 보완을 검증한 뒤 프롬프트·스키마·정답·채점 기준·설정을 고정하고 1-5를 진행한다. 이번 감사 결과만으로 새 모델 탐색이나 끝없는 프롬프트 실험을 시작하지 않는다.

## 9. 직접 확인한 것 / 확인하지 않은 것

### 직접 확인

- 요청 파일, 저장소 지침, 현재 커밋·변경 상태, 요청된 설계·코드·정답·테스트와 이전 감사 반영 기록.
- 최신 139개 단위 테스트, 10종 규칙 변이, 정답 생성기 check, 별도 경로의 rules 13문항 실행.
- 가짜 답의 실제 채점 결과, 가짜 모델의 인자 오류/예산 초과/완료 기록 손실.
- 가짜 HTTP 전송 경계에서 payload 깊은 복사, 실패 시도 집계, 원시 응답 필드 유실.
- 이전 R1~R5의 표적 재검증, 파생 반기 누적의 직접 차감, dev13의 원본 직접 계산.

### 확인하지 않음

- 실제 gpt-oss:20b 응답, 설치 모델·digest·양자화, 실제 Ollama 버전과 호환성, 실제 토큰·지연·자원 사용량.
- 실제 서버의 4개 호출/3개 결과 메시지 처리, context 초과 동작, temperature=0 반복 결정성.
- 봉인 회사 데이터, 새로운 OpenDART 응답, 캐시 이후 정정공시, 일반 재무 질문 전체의 성능.
- 비밀키 내용, 실제 키와 저장소를 대조하는 공개 안전성 검사, 배포/재배포 법률 검토.
- 이 보고서의 제안 수정. **이번 작업은 감사이며 구현을 하지 않았다.**

## 10. 산출물과 다음 행동

- 공식 결과: `docs/reviews/1-5_codex_result.ko.md` — 이 파일.
- 중단 전 원시 프로브: `<임시 폴더>/dart_review_15_yrayzbcb/`.
- 최신 커밋 재검증: `<임시 폴더>/dart_review_15_current_yp5bu_q8/`.
  - `scoring_probes.json`: 가짜 답과 채점 결과, 숫자 표기 사례, 분모 반례.
  - `runner_probes.json`: 가짜 HTTP payload, 응답, 실행/지표/예산 반례.
  - `remaining_probes.json`: 현재 코드의 중단 저장 손실, R3 상세 traceback, 숫자 누락/접수번호 반례.
  - `previous_review_probes.json`, `dev13_independent.json`: 이전 지적 재검증과 원본 직접 계산.
  - `unittest.txt`, `gold_check.txt`, `trap_tests.txt`, `rules/`: 실제 오프라인 명령 결과.
- 임시 경로는 OS가 정리할 수 있다. 중요한 재현 스크립트는 이 보고서 부록에 보존했다. 기존 평가 결과와 개발 코드의 내용은 이 감사에서 수정하지 않았다.

**현재 완료 수준:** 1-5 실행 전 감사 완료. 이전 일부 수정은 확인됐으나 새로 확인된 평가기 보완이 필요하다. 모델 가능성 판정은 아직 하지 않았다.

**이번 범위에서 남은 필수 작업:** 없음. 코드 보완은 다음 작업이다.

**사용자가 지금 할 일:** Claude에서 이어서 한다면 이 보고서를 전달하고 아래 인계문을 사용하면 된다. 사용자가 재무 금액을 직접 다시 계산할 필요는 없다. 다만 GOLD_RULES의 제품 기본값에 대한 최종 선택은 별개로 남아 있다.

**추가 프롬프트가 필요한지:** 새 검토 요청문을 따로 작성할 필요는 없다. 아래 문구를 사용할 수 있다.

> `docs/reviews/1-5_codex_result.ko.md`를 끝까지 읽고, 기준 커밋 이후 현재 변경 사항을 먼저 확인해 줘. 각 지적을 맹목적으로 적용하지 말고 재현 여부와 반영/비반영 이유를 기록해 줘. 8절의 1-5 실행 전 필수 항목을 최소 수정하고, 관련 오프라인 회귀 검증과 문서 일치를 확인해 줘. 특히 타입 오류로 평가 전체가 중단되는 문제, 오류 문구에서 금융 근거가 생성되는 문제, 본문 의미와 자동 점수의 차이, 반올림/숫자 파싱, 요청 시도 및 원시 payload 보존을 다뤄 줘. 13문항의 정답을 점수에 맞춰 바꾸지 말고, 본문 수동 검토 기준을 모델 실행 전에 고정해 줘. 기존 결과·캐시·사용자 변경 사항을 보존하고, 인증키·봉인 데이터에 접근하거나 모델/API를 실행하지 마. 이번에는 수정·검증·반영 보고서까지만 완료해 줘. 보완 후 실제 1-5 실행은 별도 단계로 남겨 줘.

**다음 권장 작업과 이유:** 평가기 보완 → 기준 고정 → 계획된 1-5 실행. 현재는 모델 성능보다 측정 오류를 제거하는 작업이 우선이다.

## 부록 A. 재현 스크립트 사용법

아래 스크립트들은 모두 저장소 바깥의 **새 임시 디렉터리**에 각각의 이름으로 저장하고 실행한다. `audit_runner.py`는 중간 결과를 생성하므로 같은 출력 디렉터리에서 반복하지 않는다. 실제 모델 이름처럼 보이는 문자열도 가짜 HTTP 응답/가짜 모델 객체 안에서만 사용한다. 이 스크립트들은 인증키 로더가 실행되면 즉시 실패하며 OpenDART 클라이언트는 offline이다.

```bash
cd <저장소>
AUDIT_DIR=$(mktemp -d -t dart-review-audit)
# 아래 4개 Python 코드 블록을 AUDIT_DIR 안에 해당 파일명으로 저장한 뒤:
python3 "$AUDIT_DIR/audit_scoring.py" "$PWD"
python3 "$AUDIT_DIR/audit_runner.py" "$PWD"
python3 "$AUDIT_DIR/audit_previous.py" "$PWD"
python3 "$AUDIT_DIR/audit_remaining.py" "$PWD"
```

이 결과를 모델 평가 JSON과 합산하지 않는다. 실제 모델 호출은 0회다. `audit_runner.py`의 원래 시점 혼합 입력은 최신 코드에서 정상적으로 문항 실패로 저장된다. 현재의 중단 반례는 `audit_remaining.py`의 별도 account 타입 오류다.

### A.1 `audit_scoring.py`

```python
"""Offline scorer audit with synthetic model answers; no network and no product writes."""
from pathlib import Path
from decimal import Decimal
import copy, json, sys
ROOT=Path(sys.argv[1]).resolve(); OUT=Path(__file__).parent
sys.path[:0]=[str(ROOT),str(ROOT/'eval')]
import run_eval
from scoring import score_case,summarize
from dart_review.numbers import allowed_from,check_text
from dart_review.answer import ANSWER_SCHEMA
from dart_review.cache import ResponseCache
from dart_review.client import DartClient

def no_key():raise AssertionError('No key allowed')
client=DartClient(ResponseCache(ROOT/'cache'),key_loader=no_key,offline=True)
spec={q['id']:q for q in json.loads(run_eval.SPEC.read_text())['questions']}
gold={g['id']:g for g in json.loads(run_eval.GOLD.read_text())['answers']}
base={}; seen={}; records=[]
for ident,q in spec.items():
 seen[ident]=[run_eval.execute_tool(client,n,a) for n,a in run_eval.interpretation_calls(q)]
 base[ident]=run_eval.rules_answer(q,seen[ident])

def probe(label,ident,updates=None,answer=None,seen_override=None,note=None):
 a=copy.deepcopy(answer if answer is not None else base[ident])
 if updates:a.update(updates)
 record={'label':label,'id':ident,'fake_answer':a,'note':note}
 try:
  record['score']=score_case(gold[ident],a,seen[ident] if seen_override is None else seen_override,spec[ident]['question']).to_dict()
 except Exception as e: record['exception']={'type':type(e).__name__,'message':str(e)}
 records.append(record);return record

# A semantically wrong visible answer for each of the 13 cases, keeping exact structural fields.
texts={
 'dev01':'2025년 매출은 300.9조 원, 2024년은 333.6조 원으로 전년보다 10.88% 감소했습니다.',
 'dev02':'2025년 6월 30일 자산총계는 523.7조 원입니다.',
 'dev03':'2025년 7~9월 3개월 영업활동현금흐름은 56.5조 원입니다.',
 'dev04':'2025년 7~9월 3개월 영업이익은 6,933억 원입니다.',
 'dev05':'연결과 별도 차이 95.6조 원은 모두 자회사 매출 때문입니다.',
 'dev06':'2023년 3분기 누적 매출은 2.16조 원입니다.',
 'dev07':'전기 영업이익은 앞 보고서와 전혀 달라지지 않았습니다.',
 'dev08':'2024년 3분기말 부채총계의 회계 기준이 실제로 바뀐 것이 확실합니다.',
 'dev09':'카카오는 흑자 전환하지 않았고 계속 적자입니다.',
 'dev10':'서버 장애라 비교할 수 없습니다.',
 'dev11':'삼성전자라는 회사가 존재하지 않아 자료가 없습니다.',
 'dev12':'영업이익으로 확정해서 답하겠습니다.',
 'dev13':'연결 기준 2025년 2분기 3개월 영업이익은 6,211억 원입니다.',
}
for ident in spec:probe('visible_wrong_'+ident,ident,{'answer':texts[ident]})
probe('visible_wrong_dev13_exact_amount','dev13',{'answer':f"연결 기준 2025년 2분기 3개월 영업이익은 {seen['dev13'][0]['current']['amount']:,}원입니다."})
for ident in ('dev01','dev04','dev07','dev08','dev10','dev11'):
 probe('no_explanation_'+ident,ident,{'answer':'확인했습니다.'})
probe('dev12_wrong_company_and_account','dev12',{'company':'카카오','account':'revenue'})
probe('dev12_synonym','dev12',{'clarifying_question':'영업이익과 순이익 중 무엇을 비교할까요?'},note='GOLD_RULES treats 순이익 as 당기순이익')
probe('dev12_money_in_prose','dev12',{'answer':f"2025년 영업이익은 {seen['dev12'][0]['current']['amount']:,}원입니다. 어느 이익인지 알려 주세요."})
probe('receipt_misclassified_amount','dev01',{'answer':'매출 증가액은 32735035000000원입니다.'})
probe('rate_as_multiple','dev01',{'answer':'매출은 전년의 10.88배입니다.'})
probe('rate_as_profit_margin','dev01',{'answer':'삼성전자의 영업이익률은 10.88%입니다.'})
probe('percent_points','dev02',{'answer':'자산총계가 전년 대비 6.6%p 증가했습니다.'})
probe('thousands_overround','dev08',{'answer':'별도 부채총계는 약 4조 원입니다.'})
probe('bare_unknown_count_ignored','dev01',{'answer':'매출 지수는 999입니다.'})
probe('correct_side_by_side','dev05')
probe('side_by_side_change_forbidden','dev05',{'change':95562929000000})
a=copy.deepcopy(base['dev02']);a['values'][0]['start']=a['values'][0]['end']
probe('mixed_instant_and_duration_crash','dev02',answer=a)
a=copy.deepcopy(base['dev02'])
for value in a['values']:value['start']=value['end']
probe('all_instants_with_same_start','dev02',answer=a)
probe('account_unhashable_crash','dev01',{'account':[]})
a=copy.deepcopy(base['dev01']);a['values'][0]={'basis':'연결','period':{'start':'2025-01-01','end':'2025-12-31'},'amount':a['values'][0]['amount']}
probe('document_nested_period','dev01',answer=a)
probe('missing_model_response','dev01',answer='not json')
summary=summarize([{'score':score_case(gold['dev01'],base['dev01'],seen['dev01'],spec['dev01']['question']).to_dict()},
                   {'score':score_case(gold['dev02'],'bad JSON',seen['dev02'],spec['dev02']['question']).to_dict()}])

number_specs=[
 ('combined_units_correct','1조 2천억 원',{'amount':1200000000000}),
 ('billions_correct_round','약 3,276억 원',{'amount':327560000000}),
 ('billions_bad_ceiling','약 3,276억 원',{'amount':327543643155}),
 ('trillion_correct_round','3.3조 원',{'amount':3275436431552}),
 ('trillion_bad_ceiling','1.3조 원',{'amount':1240000000000}),
 ('trillion_bad_floor_other_side','1.1조 원',{'amount':1190000000000}),
 ('14_digit_plain_amount','32735035000000원',{'change':32735035000000}),
 ('14_digit_comma_amount','32,735,035,000,000원',{'change':32735035000000}),
 ('8_digit_date','20250930 기준',{'period':{'end':'2025-09-30'}}),
 ('dot_date','2025.09.30 기준',{'period':{'end':'2025-09-30'}}),
 ('slash_date','2025/09/30 기준',{'period':{'end':'2025-09-30'}}),
 ('korean_date','2025년 9월 30일 기준',{'period':{'end':'2025-09-30'}}),
 ('impossible_calendar_date','2025-02-31 기준',{'period':{'end':'2025-09-30'}}),
 ('wrong_but_valid_date','2025-06-30 기준',{'period':{'end':'2025-09-30'}}),
 ('rate_vs_ratio','10.88배',{'change_pct':'10.88'}),
 ('rate_vs_points','6.6%p',{'change_pct':'6.58'}),
 ('ceiling_percent','10.9%',{'change_pct':'10.81'}),
 ('wrong_eok_man_split','3억 2천만 원',{'amount':320000000}),
 ('unhandled_magnitude','1조 2백억 원',{'amount':1020000000000}),
 ('question_numbers_allowed','999조 원',{'question':'999조 원인가요?'}),
]
number_results=[]
for label,text,source in number_specs:
 checks=check_text(text,allowed_from(source))
 number_results.append({'label':label,'text':text,'source':source,'checks':[{'kind':x.mention.kind,'text':x.mention.text,'value':str(x.mention.value),'unit':str(x.mention.unit),'grounded':x.grounded} for x in checks]})
result={'cases':records,'numbers':number_results,'denominator_probe':summary,'network_requests':client.network_requests}
(OUT/'scoring_probes.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for r in records:
 print(r['label'],r.get('exception') or {k:r['score'][k] for k in ('passed','format_error','ungrounded','warnings')})
print('DENOMINATORS',summary)
for r in number_results:print('NUMBER',r['label'],r['text'],r['checks'])
```

### A.2 `audit_runner.py`

```python
"""Fake model and HTTP-boundary probes; no actual network requests."""
from pathlib import Path
import copy,io,json,sys,urllib.error
from unittest.mock import patch
ROOT=Path(sys.argv[1]).resolve();OUT=Path(__file__).parent
sys.path[:0]=[str(ROOT),str(ROOT/'eval'),str(ROOT/'tests')]
import run_eval
from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.llm import ModelError,Reply,ScriptedChat,OllamaChat,BASE_URL
from dart_review.tools import execute_tool
from test_llm_answer_tools import FakeResponse,TAGS

def no_key():raise AssertionError('No key allowed')
client=DartClient(ResponseCache(ROOT/'cache'),key_loader=no_key,offline=True)
spec={q['id']:q for q in json.loads(run_eval.SPEC.read_text())['questions']}
gold={g['id']:g for g in json.loads(run_eval.GOLD.read_text())['answers']}
outputs={}
def run(ident,chat):return run_eval.run_case('full',spec[ident],gold[ident],client,chat)
def good(ident):
 results=[execute_tool(client,n,a) for n,a in run_eval.interpretation_calls(spec[ident])]
 return run_eval.rules_answer(spec[ident],results)
def call(ident):
 n,a=run_eval.interpretation_calls(spec[ident])[0]
 return {'function':{'name':n,'arguments':a}}
def serial(record):
 return {k:record[k] for k in ('model_requests','tool_call_count','tool_args_ok','budget_exceeded','error','score')}

class CapturingOpener:
 def __init__(self,outcomes):self.outcomes=iter(outcomes);self.payloads=[]
 def open(self,request,timeout):
  if request.full_url.endswith('/api/tags'):return FakeResponse(TAGS,request.full_url)
  if request.full_url.endswith('/api/version'):return FakeResponse({'version':'fake-0.34.4'},request.full_url)
  self.payloads.append(json.loads(request.data))
  item=next(self.outcomes)
  if isinstance(item,BaseException):raise item
  return FakeResponse(item,request.full_url)
def response(content='',calls=None):
 r={'done':True,'done_reason':'stop','model':'gpt-oss:20b','message':{'role':'assistant','content':content},
    'prompt_eval_count':123,'eval_count':34,'prompt_eval_duration':100,'eval_duration':200,'created_at':'SYNTHETIC'}
 if calls:r['message']['tool_calls']=calls
 return r

opener=CapturingOpener([response(calls=[call('dev01')]),response('확인했습니다.'),response(json.dumps(good('dev01'),ensure_ascii=False))])
chat=OllamaChat('gpt-oss:20b',opener=opener)
r=run('dev01',chat)
first=copy.deepcopy(opener.payloads[0])
outputs['payload_logs']={'per_request_message_roles':[[m['role'] for m in p['messages']] for p in opener.payloads],
 'record_message_roles':[m['role'] for m in r['messages']], 'record_keys':list(r),
 'reply_keys':list(r['replies'][0]),'reply_metadata':r['replies'][0]['metadata'],
 'first_transmitted_immutable':opener.payloads[0]==first,
 'first_payload':first,'record':r,'raw_server_first':response(calls=[call('dev01')])}
r['messages'].append({'role':'user','content':'synthetic later mutation'})
outputs['payload_logs']['first_transmitted_after_later_messages_edit']=opener.payloads[0]==first

opener=CapturingOpener([urllib.error.URLError('synthetic connection error')]);chat=OllamaChat('gpt-oss:20b',opener=opener)
r=run_eval.run_case('oracle',spec['dev01'],gold['dev01'],client,chat)
outputs['failed_http_counter']={'adapter_attempts':chat.requests,'fake_boundary_attempts':len(opener.payloads),
 'record':serial(r),'saved_reply_count':len(r['replies'])}

bad=copy.deepcopy(call('dev01'));bad['function']['arguments']['basis']='INVALID'
chat=ScriptedChat([Reply('',[bad]),Reply('',[call('dev01')]),Reply('끝'),Reply(json.dumps(good('dev01'),ensure_ascii=False))])
r=run('dev01',chat)
outputs['first_bad_then_good']={**serial(r),'tool_results':r['tool_calls']}

chat=ScriptedChat([Reply('',[call('dev01')]*4),Reply(json.dumps(good('dev01'),ensure_ascii=False))])
r=run('dev01',chat)
outputs['unresolved_batch_after_budget']={**serial(r),
 'assistant_calls':sum(len(m.get('tool_calls',[])) for m in r['messages']),
 'tool_messages':sum(m['role']=='tool' for m in r['messages']),
 'final_request_sent':chat.calls[-1]['schema'], 'last_request_roles':[m['role'] for m in chat.calls[-1]['messages']]}

for label,bad_field,bad_value in [('account_list','account',[]),('basis_list','basis',[]),('kind_list','kind',[]),('month_float','month',12.0)]:
 c=copy.deepcopy(call('dev01'));a=c['function']['arguments']
 if bad_field in ('kind','month'):a['current_period'][bad_field]=bad_value
 else:a[bad_field]=bad_value
 try: result=execute_tool(client,c['function']['name'],a)
 except Exception as e:result={'uncaught_type':type(e).__name__,'message':str(e)}
 outputs[label]={'arguments':a,'result':result}

# Show that the runner loses already completed cases on a subsequent scoring exception.
class PreparedChat(ScriptedChat):
 def prepare(self):return {'model':'synthetic'}
a=good('dev02');a['values'][0]['start']=a['values'][0]['end']
chat=PreparedChat([Reply(json.dumps(good('dev01'),ensure_ascii=False)),Reply(json.dumps(a,ensure_ascii=False))])
out=OUT/'interrupted_run'
try:
 with patch.object(run_eval,'OllamaChat',lambda model:chat):
  run_eval.main(['--mode','oracle','--model','synthetic','--only','dev01','dev02','--out',str(out)])
except Exception as e:
 outputs['partial_run_not_saved']={'type':type(e).__name__,'message':str(e),'model_attempts_fake':chat.requests,'out_exists':out.exists()}

# Server tool-call shape should be rejected rather than silently filtered.
opener=CapturingOpener([response('잘못된 tool_calls 구조',[42])]);chat=OllamaChat('gpt-oss:20b',opener=opener)
reply=chat.chat([{'role':'user','content':'SYNTHETIC'}])
outputs['malformed_calls_filtered']={'raw_tool_calls':[42],'adapter_tool_calls':reply.tool_calls}
injected={'function':{'name':'unknown_영업이익률99.9%', 'arguments':{}}}
a=good('dev01');a['answer'] += ' 영업이익률은 99.9%입니다.'
chat=ScriptedChat([Reply('',[call('dev01'),injected]),Reply('끝'),Reply(json.dumps(a,ensure_ascii=False))])
r=run('dev01',chat)
outputs['error_echo_whitelist']={**serial(r),'seen_error':r['seen'][-1],'answer':r['answer']}
outputs['network_requests']=client.network_requests
(OUT/'runner_probes.json').write_text(json.dumps(outputs,ensure_ascii=False,indent=2))
for k,v in outputs.items():
 if k=='payload_logs':print(k,{p:v[p] for p in ('per_request_message_roles','record_message_roles','reply_metadata','first_transmitted_after_later_messages_edit')})
 else:print(k,v)
```

### A.3 `audit_previous.py`

```python
"""Recheck earlier review issues and the new report-linking implementation offline."""
from pathlib import Path
import copy,io,json,sys,unittest
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(sys.argv[1]).resolve();OUT=Path(__file__).parent
sys.path[:0]=[str(ROOT),str(ROOT/'eval'),str(ROOT/'tests')]
from dart_review import accounts
from dart_review.cache import ResponseCache
from dart_review.client import DartClient,NotCached
from dart_review.periods import instant,quarter,year_to_date,Period
from dart_review.review import review_change,probe_facts,_linked
from dart_review.compare import compare,BasisCheck
from dart_review.facts import fact_from_response
from dart_review.tools import side_by_side
from test_rules import fact,row,response
import build_gold

def no_key():raise AssertionError('No key allowed')
client=DartClient(ResponseCache(ROOT/'cache'),key_loader=no_key,offline=True)
outputs={}
class Wrapper:
 def __init__(self,mode):self.mode=mode
 def financial_statements(self,corp,year,report,basis):
  r=client.financial_statements(corp,year,report,basis)
  if (year,report)==(2024,'11011'):
   if self.mode=='missing':raise NotCached('SYNTHETIC')
   if self.mode=='013':return replace(r,status='013',body=b'{"status":"013","list":[]}')
   if self.mode=='empty':return replace(r,body=b'{"status":"000","list":[]}')
  return r
for mode in ('normal','missing','013','empty'):
 r=review_change(client if mode=='normal' else Wrapper(mode),'00413046','OFS','total_liabilities',instant(2025,9),instant(2024,9))
 outputs['R1_'+mode]={'status':r.status,'reasons':r.reasons,'notes':r.notes}
spec=json.loads(build_gold.SPEC.read_text())
q=copy.deepcopy(next(q for q in spec['questions'] if q['id']=='dev08'))
q['expected']['evidence']['restated_pair']['cells']=[copy.deepcopy(q['expected']['evidence'][k]) for k in ('current','base')]
try:build_gold.build_question(client,q);outputs['R2']='WRONGLY ACCEPTED'
except build_gold.GoldError as e:outputs['R2']={'rejected':str(e)}
original=Period.label
with patch.object(Period,'label',lambda p:original(p) if p.is_instant else 'WRONG FLOW PERIOD'):
 document,problems=build_gold.build(client,spec)
outputs['R2_period_label']={'problems_count':len(problems),'example':problems[0] if problems else None}
with patch.object(accounts,'_is_total_row',lambda r:True):
 suite=unittest.defaultTestLoader.loadTestsFromName('test_rules.ResolutionTests.test_breakdown_rows_in_the_same_statement_are_ignored')
 result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
 outputs['R3']={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}
r=accounts.resolve_account([row('IS','ifrs-full_ProfitLossAttributableToOwnersOfParent','당기순이익',thstrm='99')],'net_income')
outputs['R4']={'method':r.method,'notes':r.notes}
r=compare(replace(fact(120),currency=None),replace(fact(100,quarter(2024,9)),currency=None))
outputs['R5']={'status':r.status,'reasons':r.reasons}

# Current and comparative derived YTD values must equal independent subtraction.
resp=client.financial_statements('00258801',2023,'11014','CFS')
raw=next(r for r in resp.json()['list'] if r['sj_div']=='CIS' and r['account_nm']=='영업수익' and r['account_detail']=='-')
probes=probe_facts(resp,'revenue'); derived=[f for f in probes if f.resolved_by=='derived']
independent=[int(raw['thstrm_add_amount'])-int(raw['thstrm_amount']),int(raw['frmtrm_add_amount'])-int(raw['frmtrm_q_amount'])]
outputs['derived_amounts']={'actual':[f.amount for f in derived],'independent':independent,'periods':[f.period.label() for f in derived],
 'sources':[f.source.column for f in derived]}
bridge=probe_facts(client.financial_statements('00258801',2023,'11012','CFS'),'revenue')
outputs['dev06_linked']=_linked(probes+bridge,resp.json()['list'][0]['rcept_no'],bridge[0].rcept_no)
f1=derived[0]
outputs['different_period_same_number_not_linked']=_linked([f1,replace(f1,period=year_to_date(2023,3),rcept_no='SYNTHETIC_OTHER')],f1.rcept_no,'SYNTHETIC_OTHER')
outputs['different_currency_same_number_not_linked']=_linked([f1,replace(f1,currency='USD',rcept_no='SYNTHETIC_OTHER')],f1.rcept_no,'SYNTHETIC_OTHER')

class CurrencyMismatch:
 def financial_statements(self,corp,year,report,basis):
  r=client.financial_statements(corp,year,report,basis)
  if basis=='OFS':
   d=r.json()
   for row_ in d['list']:row_['currency']='USD'
   return replace(r,body=json.dumps(d,ensure_ascii=False).encode())
  return r
s=side_by_side(CurrencyMismatch(),'삼성전자','revenue',{'kind':'year_to_date','year':2025,'month':12})
outputs['side_by_side_currency_bypass']={'status':s['status'],'currencies':[f['currency'] for f in s['values']],
 'difference':s['difference'],'meaning':s['difference_meaning'],'rule_status':s['rule_status_for_change']}
outputs['network_requests']=client.network_requests
(OUT/'previous_review_probes.json').write_text(json.dumps(outputs,ensure_ascii=False,indent=2))
for k,v in outputs.items():print(k,v)
```

### A.4 `audit_remaining.py`

```python
"""Additional offline probes after commit 8c19b82; do not modify repository files."""
from pathlib import Path
import copy, io, json, sys, unittest
from unittest.mock import patch

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(__file__).parent
sys.path[:0] = [str(ROOT), str(ROOT / 'eval'), str(ROOT / 'tests')]
import run_eval
from dart_review import accounts
from dart_review.cache import ResponseCache
from dart_review.client import DartClient
from dart_review.llm import ScriptedChat, Reply
from dart_review.numbers import allowed_from, check_text
from scoring import score_case

def no_key():
    raise AssertionError('No key allowed')

client = DartClient(ResponseCache(ROOT / 'cache'), key_loader=no_key, offline=True)
questions = {q['id']: q for q in json.loads(run_eval.SPEC.read_text())['questions']}
gold = {g['id']: g for g in json.loads(run_eval.GOLD.read_text())['answers']}
def good(ident):
    q = questions[ident]
    results = [run_eval.execute_tool(client, n, a) for n, a in run_eval.interpretation_calls(q)]
    return run_eval.rules_answer(q, results)

results = {}
class PreparedChat(ScriptedChat):
    def prepare(self):
        return {'model': 'synthetic-offline'}

answer = good('dev02')
answer['account'] = []
chat = PreparedChat([Reply(json.dumps(good('dev01'), ensure_ascii=False)),
                     Reply(json.dumps(answer, ensure_ascii=False))])
out = OUT / 'interrupted_account_error_run'
assert not out.exists()
try:
    with patch.object(run_eval, 'OllamaChat', lambda model: chat):
        run_eval.main(['--mode', 'oracle', '--model', 'synthetic-offline', '--only', 'dev01', 'dev02', '--out', str(out)])
except Exception as exc:
    results['partial_run_not_saved_current'] = {
        'exception_type': type(exc).__name__, 'error': str(exc),
        'fake_model_attempts': chat.requests, 'out_exists': out.exists(),
    }

with patch.object(accounts, '_is_total_row', lambda row: True):
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromName('test_rules.ResolutionTests.test_breakdown_rows_in_the_same_statement_are_ignored')
    result = unittest.TextTestRunner(stream=stream).run(suite)
    results['R3_mutation'] = {'tests': result.testsRun, 'failures': len(result.failures),
                              'errors': len(result.errors), 'output': stream.getvalue()}

for text in ('1조 9백억 원', '1조 2백억 원'):
    checks = check_text(text, allowed_from({'amount': 1_020_000_000_000}))
    results[text] = [{'text': c.mention.text, 'kind': c.mention.kind,
                      'grounded': c.grounded} for c in checks]

# The 14-digit fix recognizes a correct amount, but still treats a real receipt as a currency amount.
ident = 'dev01'
seen = [run_eval.execute_tool(client, n, a) for n, a in run_eval.interpretation_calls(questions[ident])]
answer = good(ident)
answer['answer'] = '이번 매출액은 20260310002820원입니다.'
results['receipt_as_currency'] = {'fake_answer': answer,
    'score': score_case(gold[ident], answer, seen, questions[ident]['question']).to_dict()}

results['network_requests'] = client.network_requests
(OUT / 'remaining_probes.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print(json.dumps(results, ensure_ascii=False, indent=2))
```

## 부록 B. 보존 확인

- 재개 시점의 추적 파일 48개를 SHA-256으로 비교했으며 내용 변경 0개다.
- 중단 중 들어온 `8c19b82`의 사용자/Claude 변경은 그대로 유지했다. 기존 `7a8443d`와의 차이를 이번 감사가 만든 변경으로 세지 않았다.
- 저장소에 추가한 것은 이 감사 보고서 한 파일이다. 감사 실행 코드와 원시 출력은 위 별도 임시 경로에 생성했다.
