# D4 계약·v0.2 코드 독립 검토 결과

- 검토일: 2026-10-10. 대상: `6e8528d^..78f7b76`, `docs/EVAL_CONTRACT_D4.ko.md`, `eval/documents_2026-10-10/`.
- 범위: 정적 검토, 임시 합성 입력, 기존 세 테스트의 옛 커밋 재현, 지정된 여섯 PDF의 규칙 방식 오프라인 재측정. OpenDART API, 인증키, Ollama, 봉인 3-1 재평가를 사용하지 않았다. 추적 파일은 수정하지 않았다.
- 판단: **현 계약을 그대로 사전 등록해 S1·S2의 `0`을 제품 정확성의 합격으로 해석하면 안 된다.** 실제 제품의 조용한 누락과, 이를 정답으로 놓칠 수 있는 채점 규칙이 각각 확인됐다. 아래의 재현은 합성 반례이며 실제 신규 10개 회사에서의 발생률을 뜻하지 않는다.

## 평가 전에 고칠 것

### 1. [치명] 한두 자리 금액의 행이 문제 기록 없이 사라진다

- **위치:** `dart_review/documents/statement.py:235-277, 308-319`; `dart_review/documents/table.py:152-164`.
- **근거:** `read_statement`는 열에 놓이지 않은 금액을 `_is_note_like`가 참이면 고아 금액으로 세지 않는다. 그 함수는 기간 열의 위치를 검사하기 전에 `\d{1,2}`를 무조건 주석 번호로 본다. 임시 `Word`/`Line`으로 만든 손익계산서에서 당기·전기 두 열은 정상적으로 찾고 매출액·영업이익 두 행은 읽혔다. 오른쪽 끝이 기존 금액 열보다 40 좌표만큼 어긋난 `기본주당이익 | 47`을 추가하자 실행 결과가 `rows=[매출액, 영업이익]`, `problems=[]`였다. `47` 행과 값은 사라졌다. 이는 전체 PDF가 아닌 함수 수준 반례이며, 동일한 열 어긋남이 실제 문서에 얼마나 있는지는 확인하지 않았다.
- **제안:** 한두 자리 금액을 열 위치와 행 맥락을 확인하지 않고 주석으로 간주하지 않는다. 행 이름이 있고 금액처럼 보이는 숫자를 배치하지 못하면 행 또는 해당 원문 숫자를 `problems`에 남긴다. 작은 금액과 진짜 주석 번호를 분리하는 회귀 테스트를 둔다.

### 2. [치명] D4 정답 규칙이 다른 계정의 같은 숫자와 부호 반전을 맞음으로 센다

- **위치:** `docs/EVAL_CONTRACT_D4.ko.md:54-72, 78-84`; `eval/measure_documents.py:68-81, 119-130, 145-151`.
- **근거:** 계약의 칸 단위에는 **행**이 포함되지만 `dart_value`는 같은 기간·같은 값이면 다른 계정도 맞음이고, `dart_sign`은 모든 재무제표 종류에 허용된다. 합성 `classify` 호출에서 `매출액=1,000`, OpenDART `영업이익=1,000`은 `dart_value=1`; 재무상태표 `자산총계=-1,000`, OpenDART `자산총계=+1,000`은 `dart_sign=1`이었다. 둘 다 틀린 행 또는 틀린 부호를 S1에서 제외한다. 보고서가 이미 공개한 사진의 `유동부채`→`부채` 오표기도 `dart_value`로 맞음 처리됐다(`eval/documents_2026-10-10/REPORT.ko.md:125`). 작은 값만 별도 집계해도 큰 값의 우연한 일치와 계정명 오류는 해결되지 않는다.
- **제안:** 기본 정답은 (재무제표, 행 식별자/검토된 계정명, 기간, 부호 포함 값)으로 대조한다. 표기만 다른 동일 행은 실행 전에 대응표를 고정하거나 독립 검토 대상으로 보낸다. 부호 예외는 현금흐름표의 사전 지정 계정·표현에 한정하고, 나머지는 틀림/검토 대상으로 둔다. 계정명 오류도 S1과 별도 공식 지표로 남긴다.

### 3. [치명] 같은 값이 다른 행에 있으면 빠진 행이 S2 후보에서도 사라진다

- **위치:** `docs/EVAL_CONTRACT_D4.ko.md:70-71, 79`; `eval/measure_documents.py:118-123, 149-151`.
- **근거:** `ours[period]`는 행이 없는 값의 집합이다. 합성 재무상태표에서 OpenDART의 `유동자산=1,000`과 `비유동자산=1,000` 중 출력에는 유동자산만 두었는데 `dart_not_extracted=[]`였다. 따라서 사람이 원본과 비교할 빠진 후보 자체가 생기지 않는다. 표시 정의도 ‘그 숫자를 읽지 않았다는 문제가 그 재무제표의 문제 목록에 있으면’으로 되어 있어, 같은 숫자가 여러 행·기간에 있을 때 어느 빈 칸을 가리키는지, 포괄적인 띠 실패 메시지가 표시로 인정되는지 확정돼 있지 않다. **실제 D4 채점기는 아직 없으므로 포괄 메시지로 오채점한 사례를 관찰한 것은 아니다.**
- **제안:** 빠진 칸을 (문서, 재무제표, 행, 기간)으로 찾고 동일 금액의 중복 발생 수까지 보존한다. 표시 인정은 해당 행·기간 또는 원본 쪽/줄/금액에 연결된 경고로 제한한다. `AI가 한 부분을 읽지 못했다`처럼 어느 금액인지 모르는 메시지는 별도의 문서 수준 경고로 세되 S2의 개별 칸 표시로 자동 대체하지 않는다.

### 4. [중요] `pdf_only`는 같은 텍스트 줄의 숫자 존재만으로 기간·단위 오류를 덮을 수 있다

- **위치:** `eval/measure_documents.py:84-91, 131-141`; `docs/EVAL_CONTRACT_D4.ko.md:57, 65`.
- **근거:** `printed_on_page`가 페이지의 글자를 좌표 없이 한 문자열로 합치고, `classify`는 `key[:6]`와 인쇄 숫자가 한 줄에 있으면 `pdf_only`로 맞음 처리한다. 합성 입력에서 원본 줄 `매출액1,0002,000`, 출력의 당기값 `2,000`, OpenDART 당기 `9,999`를 넣자 `pdf_only=1`이었다. 텍스트 줄에 그 숫자가 있는 것은 확인했지만 당기 열의 숫자인지는 확인하지 않았다. `wrong_period` 분기는 다른 기간의 OpenDART에 동일 값이 있을 때만 이 사례를 먼저 잡는다.
- **제안:** PDF 글자 기반 예외도 행·기간 열 좌표와 단위를 함께 확인한다. 그 연결이 불확실하면 맞음으로 확정하지 않고 사람 검토로 보낸다. 원본 인쇄본과 OpenDART가 다를 수 있다는 이유만으로 임의의 같은 줄 숫자를 정답으로 만들지 않는다.

### 5. [중요] 사진의 OCR 증거는 같은 행을 보장하지 않으며, 누락된 OCR 숫자를 역검사하지 않는다

- **위치:** `dart_review/documents/ai_reader.py:374-427, 430-471`; `dart_review/documents/excel.py:40-44`; `dart_review/upload.html:42-45`.
- **근거:** `_add_row_by_tokens`는 띠 안의 어느 높이에 있든 같은 숫자 토큰 하나만 찾으면 `evidence="OCR"`인 `검사 통과` 칸을 만든다. 합성 호출에서 OCR 숫자 `1,000`이 다른 행의 위치에 있고 모델이 `매출액 | 1,000`이라고 답해도 `검사 통과`, 이유 `[]`, 재무제표 문제 `[]`였다. 계정명 OCR 대조도 없다. 반대로 사진 경로는 텍스트 경로의 `claimed` 미청구 금액 순회(`ai_reader.py:366-369`)가 없어서, 띠에 OCR 숫자가 있어도 모델이 행을 누락한 경우 금액별 경고가 만들어지지 않는다. 실패한 띠는 포괄 경고만 남긴다고 개발 보고서도 명시한다(`REPORT.ko.md:68`). 엑셀 안내의 ‘각 숫자를 ... 같은 줄과 대조’와 업로드 화면의 ‘모든 숫자는 원본과 대조’는 사진 경로의 실제 보증보다 강하다.
- **제안:** OCR 금액과 계정명 후보가 같은 높이·열에 있는지 확인한다. OCR이 흐려 위치가 불확실하거나 동일 숫자가 여러 줄에 있으면 통과시키지 않고 칸을 표시한다. 미청구 OCR 숫자도 주석과 본문을 구별할 수 있는 범위에서 금액별 또는 위치별 경고로 남긴다. 개선 전에는 제품 안내를 사진 경로의 실제 검증 강도에 맞춰 고친다.

### 6. [중요] 사진에서 서로 다른 동일 이름·동일 값 행이 띠 중복으로 합쳐질 수 있다

- **위치:** `dart_review/documents/ai_reader.py:196-217, 416-424, 439-455`.
- **근거:** 증거 줄이 없는 사진 경로의 `_existing_row`는 최근 행에서 정규화 계정명이 같으면 즉시 기존 행으로 결정한다. 모델이 두 띠에서 실제로 다른 두 `매출액 | 1,000` 행을 읽었다는 합성 호출 결과는 `rows=1`, `checks=1`, 둘째 OCR 토큰 `claimed=False`, 문제 `[]`였다. 금액이 다르면 기존 칸을 표시하지만, 같은 값이면 새 행이 조용히 사라진다. 숫자가 같고 계정명만 다른 경우에도 최근 숫자 순서가 같으면 병합한다(`:208-216`). 이는 실제 사진에서 발생했다고 단정하는 결과가 아니라 현 구현의 재현 가능한 반례다.
- **제안:** 띠 겹침을 계정명·숫자만으로 판단하지 말고 페이지 위치와 실제 OCR 토큰의 동일성으로 제한한다. 위치 근거가 약하면 두 행을 보존하고 중복 가능성을 표시한다.

### 7. [중요] 숫자만으로 소계의 세부 행을 접어 검산 실패를 숨길 수 있다

- **위치:** `dart_review/documents/verify.py:89-160`.
- **근거:** `_collapsed([10, 5, 5])` 실행 결과는 `[10]`이고 원래 합은 `20`이다. 세부 행의 첫 `10`이 우연히 뒤의 `5+5`와 같으면 레이블·들여쓰기·부모 관계 확인 없이 뒤 두 행을 중복 층으로 취급한다. 소계 `10`이 실제 세부 세 행 `10+5+5=20`과 불일치해도 검산은 `10=10`으로 통과할 수 있다. 또한 `_subtotals`가 위치 분리를 못하면 그 구간은 검사하지 않는다. 현재 개발 PDF에서 이 우연한 수치 배열을 발견한 것은 아니다.
- **제안:** 접기는 표 구조의 하위 행 관계가 확인될 때만 허용한다. 숫자 일치만 있는 구간은 검산 불가 또는 확인 필요로 남기고, 소계 검사가 수행된 비율을 D4에 보고한다.

### 8. [중요] 표본 선정·정답 수정의 기록이 재현 가능한 수준으로 고정되지 않았다

- **위치:** `docs/EVAL_CONTRACT_D4.ko.md:15-24, 39-46, 87-96, 106-117`.
- **근거:** ‘고정 시드’만 있고 KOSPI 모집단의 출처·기준일·정렬, 중복/비상장/업종 제외 판정, 첫 10곳의 전체 후보 순서, ‘첨부 없음’ 판정 기준이 없다. 따라서 PDF를 내려받거나 읽어본 뒤 후보를 건너뛸 여지가 있다. 정답은 문서를 본 뒤 사전 등록 전에 만들므로, OpenDART와 인쇄본의 차이 및 `pdf_only` 사례를 어떤 기준으로 받아들일지 사람 판단도 결과에 영향을 줄 수 있다. 합성 스캔은 원본 문서 전체가 아니라 재무제표 페이지만 포함하면서 정답을 재사용한다. 생성 시 페이지 누락·잘림·가독성 변화를 확인하는 규칙이 없다.
- **제안:** 사용자 승인 뒤 문서를 받기 전에 모집단 파일·SHA, 순서 생성 코드·시드, 제외 목록과 대체 순서를 고정한다. 내려받을 수 없다는 판단도 후보별 근거를 기록한다. 정답은 칸별 인쇄 위치와 OpenDART 근거를 제품 출력과 독립적으로 적고, 불일치 허용 기준·수정 이력을 사전 등록에 포함한다. 합성 스캔은 원본 페이지와 매핑, 잘림·누락 검사를 기록하고 S1을 채점한다. Claude 1차 판정은 도움 자료로 두되 최종 사람 확인과 변경 이력을 남긴다. 회사 10곳은 표본 사례이지 일반적인 오류율의 정밀 추정으로 표현하지 않는다.

### 9. [중요] 완료 작업 삭제가 실행 상태 변경 및 파일 제거 실패와 원자적으로 연결되지 않는다

- **위치:** `dart_review/server.py:122-140, 184-197`.
- **근거:** `delete`는 잠금 밖에서 상태를 읽은 뒤 파일을 지우고, 마지막에 잠금 안에서 DB 행을 지운다. 임시 DB에서 `get`이 `done`을 반환한 직후 `running`으로 상태를 바꾸도록 한 합성 경쟁 시험에서는 `running` 작업의 폴더와 DB 행이 삭제됐다. `shutil.rmtree(..., ignore_errors=True)`가 실패를 조용히 반환하는 경우를 모사하자 DB 행은 없어졌지만 `source.pdf`는 남았다. 후자는 문서 보관·삭제 약속에 직접 영향을 준다. 실제 웹 요청 부하에서 재현 빈도는 측정하지 않았다.
- **제안:** 같은 잠금/조건부 DB 전이 아래에서 삭제 가능 상태를 재검증하고 작업을 삭제 중으로 예약해 worker와 경합하지 않게 한다. 파일 제거 실패를 확인하고 DB 기록을 남겨 재시도할 수 있게 한다. 재시작 후 대기 작업 처리 정책도 명시한다.

## 기록만 할 것

### 10. [사소] 개발 보고서의 규칙 방식 시간은 저장 JSON과 일치하지 않는다

- **위치:** `eval/documents_2026-10-10/REPORT.ko.md:42-51, 65-66, 81-85`; 같은 폴더의 `rules.json`, `ai.json`; `docs/EVAL_CONTRACT_D4.ko.md:28`.
- **근거:** JSON 직접 집계에서 규칙 방식 `seconds`는 삼성전자/NAVER/한화시스템/포스코/LG에너지솔루션/사진 순서로 `4/6/2/2/2/54`인데 보고서 표는 `4/7/3/2/2/68`이다. `rules.json`의 `cells`는 `240/266/240/276/428/0`, 보고서 ‘칸’은 `236/254/230/270/417/0`이다. 후자는 대시·값 없음 등을 제외한 `classes` 합계와 일치한다. 따라서 칸 수는 서로 다른 정의이며 단순 숫자 오기는 아니다. AI의 표 수치와 분류 합계는 저장 JSON과 맞았다. 두 JSON의 `code_commit`은 `b774c60`인데 D4 계약은 ‘개발 측정 때의 코드’를 `8b0a7bd`라고 적는다. 사진 요약의 ‘틀린 칸은 모두 표시’는 바로 뒤 7절이 인정한 표시 없는 계정명 오류를 독자가 놓치게 할 수 있다.
- **제안:** 보고서 규칙 시간은 원본 JSON으로 정정하거나 다른 실행 기록이면 명시한다. `cells`와 ‘분류된 숫자 칸’의 분모 차이를 표 머리말에 적는다. 계약에는 첫 측정 `8b0a7bd`와 최종 저장 측정 `b774c60`을 구분한다. ‘틀린 칸 모두’는 ‘현 분류기가 틀림·미확인으로 잡은 칸 모두’로 한정한다. 개발 측정이라는 표시는 현재 문서에 명확하다.

### 11. [중요, 잠재 위험] 서버가 임의 `RuntimeError`의 문구를 저장·노출한다

- **위치:** `dart_review/server.py:196-205, 208-212`; `dart_review/documents/words.py:34`, `dart_review/documents/vision.py:47`.
- **근거:** `_error_message(RuntimeError('synthetic private document text'))` 결과가 동일한 문자열이었다. 이 문구는 SQLite `jobs.error`와 `/jobs`, `/jobs/{id}`에 그대로 포함된다. 현재 기본 `DocumentError`·`VisionError` 구현에서 실제 문서 내용이 예외에 들어가는 경로는 발견하지 못했다. 따라서 **실제 유출을 확인했다는 뜻은 아니다.** 다만 `Worker`의 모든 `RuntimeError`를 안전하다고 가정하는 것은 유지 보수 시 깨질 수 있다.
- **제안:** 공개 메시지는 사전 정의한 안전한 오류 코드·문구만 허용한다. 예외 원문을 로깅해야 한다면 접근 범위를 제한하고 문서 텍스트가 섞이지 않도록 한다.

### 12. [사소] 업로드 화면에는 인증이 없다는 안내가 없고 PDF 판별은 표지 검사뿐이다

- **위치:** `dart_review/upload.html:42-45`; `dart_review/server.py:97-115, 240-252`; `README.ko.md:183`.
- **근거:** README는 `127.0.0.1, 계정 없음`이라고 밝힌다. 실제 CLI의 `serve --host`는 루프백 주소만 허용한다(`dart_review/__main__.py:114-117, 143-146`). 하지만 업로드 화면은 ‘이 컴퓨터 안에서만 처리’만 말한다. 임시 `JobStore`는 `%PDF-1.4\nsynthetic` 바이트를 업로드로 받아 `queued`로 저장했다. 전체 PDF 유효성은 worker가 뒤에 판단하므로 사용자는 업로드 성공을 유효한 PDF 판정으로 오해할 수 있다. 이 점이 곧 경로 조작 취약점은 아니다. 작업 ID는 32자리 소문자 16진수만 허용하고 실제 파일명은 고정 `source.pdf`다.
- **제안:** 화면에 루프백 전용·인증 없음·로컬 데이터 보존을 짧게 적는다. PDF 판별은 ‘형식 후보로 접수’와 ‘실제 읽기 성공’을 구분한다. 파일명은 표시용으로만 쓰고 있다는 점을 유지한다.

## 확인한 검증과 범위

- **옛 코드 표본:** 격리된 임시 `git worktree`에 현행 `tests/test_ai_reader.py`를 복사하여 `c6f887b^`의 반복 계정명 시험은 실패(둘째 행 누락), `8b0a7bd^`의 머리글 위치 시험은 실패(`[0,0,1,1,1]` 대 기대 `[None,0,0,1,1]`), `b774c60^`의 한 페이지 두 재무제표 시험은 오류(두 번째 표 없음)였다. 임시 worktree는 제거했다. 현행 `.venv/bin/python -m unittest tests.test_documents tests.test_ai_reader tests.test_server`는 **47개 통과**했다. 이는 위 새 반례를 테스트한다는 뜻은 아니다.
- **규칙 방식 재실행:** `.venv/bin/python eval/measure_documents.py --pdf-dir ~/Desktop/감사보고서 --reader rules --out /tmp/d4_codex_rules_20261010`을 오프라인으로 실행했다. 스크립트가 지정한 여섯 PDF만 읽었다. 각 파일의 SHA-256은 저장 `rules.json`과 모두 같았다. 두 JSON의 문서별 결과는 실행시간을 제외하고 같았고, 사진 PDF 시간만 저장 `54초` 대 재실행 `52초`였다. AI 방식은 실행하지 않았다.
- **API·화면:** 파일 크기는 `MAX_UPLOAD_BYTES+1`만 읽고 상한을 검사한다. `JobStore`는 매 호출마다 새 SQLite 연결을 만들며 쓰기는 잠금으로 감싼다. 보고서 JSON의 계정명은 DOM `createTextNode`로 넣고 `innerHTML`을 쓰지 않아, 검사한 렌더링 경로에서는 계정명 XSS를 찾지 못했다. 실제 브라우저 공격 시험과 다중 요청 부하 시험은 하지 않았다.
- **평가 한계:** 신규 평가 문서를 선정·다운로드하지 않았고, D4 금지 조건에 따라 모델·API 호출을 하지 않았다. 따라서 10곳의 S1·S2, 사진 경로의 실제 빈도, OCR 계정명 대조의 오탐률은 아직 모른다. 이번 결과는 D4를 시작하기 전에 계약과 구현의 검출 구멍을 고칠 근거다.

## 합성 반례 재현 명령

아래 명령은 저장소 루트에서 `.venv`가 있는 상태로 실행한다. 실제 PDF, 제품 DB, 모델을 사용하지 않는다.

```bash
./.venv/bin/python - <<'PY'
from dart_review.documents.statement import read_statement
from dart_review.documents.table import Cell, Line
from dart_review.documents.words import Word
def line(y, entries):
    return Line(1, [Cell([Word(text, 1, x0, x1, y, y+10)]) for text, x0, x1 in entries])
title = line(0, [('손익계산서', 20, 100)])
body = [line(15, [('(단위: 원)', 20, 90)]),
        line(30, [('당기', 300, 350), ('전기', 500, 550)]),
        line(50, [('매출액', 20, 80), ('1,000', 310, 350), ('2,000', 510, 550)]),
        line(70, [('영업이익', 20, 100), ('3,000', 310, 350), ('4,000', 510, 550)]),
        line(90, [('기본주당이익', 20, 100), ('47', 365, 390)])]
s = read_statement(title, body, [title, *body])
print([r.label for r in s.rows], s.problems)
PY
```

출력: `['매출액', '영업이익'] []` (발견 1).

```bash
./.venv/bin/python - <<'PY'
from types import SimpleNamespace as N
from eval.measure_documents import classify
def classify_one(kind, label, value, dart_items, lines=None):
    amount = N(value=value, printed=f'{abs(value):,}', cell=N(page=1))
    statement = N(kind=kind, title='연결'+{'BS':'재무상태표','IS':'손익계산서'}[kind],
                  page=1, rows=[N(label=label, amounts={0:amount})], problems=[])
    return classify(N(statements=[statement], checks=[]), {'CFS':dart_items}, lines or {})['statements'][0]
print(classify_one('IS', '매출액', 1000,
      [{'sj_div':'IS','account_nm':'영업이익','thstrm_amount':'1000'}])['classes'])
print(classify_one('BS', '자산총계', -1000,
      [{'sj_div':'BS','account_nm':'자산총계','thstrm_amount':'1000'}])['classes'])
print(classify_one('BS', '유동자산', 1000,
      [{'sj_div':'BS','account_nm':'유동자산','thstrm_amount':'1000'},
       {'sj_div':'BS','account_nm':'비유동자산','thstrm_amount':'1000'}])['dart_not_extracted'])
print(classify_one('IS', '매출액', 2000,
      [{'sj_div':'IS','account_nm':'매출액','thstrm_amount':'9999'}],
      {1:['매출액1,0002,000']})['classes'])
PY
```

출력의 해당 분류·목록: `dart_value=1`, `dart_sign=1`, `[]`, `pdf_only=1` (발견 2–4). 이 시험은 분류기의 통과 조건만 입증하며 실제 PDF의 값이 틀렸다는 주장은 아니다.

```bash
./.venv/bin/python - <<'PY'
from dart_review.documents.ai_reader import _add_row_by_tokens, Part
from dart_review.documents.statement import Statement, PeriodColumn
from dart_review.documents.vision import BandLine
from dart_review.documents.words import Word
s = Statement('IS', True, '손익계산서', 1, 1, '원', [PeriodColumn('당기')], [], [])
part = Part(1, None, [], 'OCR', (0,600), [])
checks, claimed = [], set()
first = Word('1,000', 1, 400, 450, 100, 110, 'ocr', 99)
_add_row_by_tokens(s, checks, 0, BandLine('매출액',['1,000']), [first], part, claimed, 0)
print(len(s.rows), [(c.status,c.evidence,c.reasons) for c in checks])
second = Word('1,000', 1, 400, 450, 140, 150, 'ocr', 99)
_add_row_by_tokens(s, checks, 0, BandLine('매출액',['1,000']), [second], part, claimed, 0)
print(len(s.rows), len(checks), id(second) in claimed, s.problems)
PY
```

출력: `1 [('검사 통과', 'OCR', [])]`, 이어서 `1 1 False []` (발견 5–6). 두 번째 OCR 토큰이 별개 행이라는 가정 아래 병합 반례다.

```bash
./.venv/bin/python - <<'PY'
from dart_review.documents.verify import _collapsed
print(_collapsed([10,5,5]), sum([10,5,5]))
PY
```

출력: `[10] 20` (발견 7). 서버 경쟁·파일 제거 실패 시험은 실제 파일 대신 `TemporaryDirectory`의 합성 `%PDF-` 입력과 `unittest.mock.patch`로 재현했다(발견 9). README/화면/API는 정적 검사했고, 브라우저 공격이나 실제 사용자 PDF로 재시험하지 않았다.
