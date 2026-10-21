# D5 계약·도구 Codex 재검토 결과

- 검토일: 2026-10-20
- 대상: `git diff 1547a2c..HEAD`, 1차 결과와 응답, `docs/EVAL_CONTRACT_D5.ko.md` 초안 2판
- 제약: 인증키·OpenDART 요청·Ollama·네트워크를 쓰지 않았다. 제품 추출, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행은 하지 않았다. D4 PDF에는 정답 생성기와 위치 검사만 썼고, 저장된 제품 보고서만 다시 집계했다.

## 결론

1차 7건 가운데 **5번과 6번은 닫혔고, 4번은 문제의 거짓 양성 경로가 닫혔다. 1번과 2번은 일부만 닫혔으며, 3번은 지정 태그를 조회하는 기능은 생겼지만 등록 기록과의 결합이 남았다. 7번은 수치 문구는 고쳤지만 고정 커밋 표기는 아직 없다.**

고정 전 결과는 **치명 1건, 중요 2건**이다. 계약에는 **사소 1건**을 더 적어야 한다. 가장 큰 문제는 `expected_documents`가 문서 목록 자체의 자기 선언이라서, 10개로 결정한 뒤 1개나 9개만 넣고 그 숫자도 함께 줄이면 여전히 그 일부 표본으로 `met`이 가능하다는 점이다.

## 고정 전에 반드시 고칠 것

### 1. [치명] 문서 수를 목록이 스스로 정하므로 일부 표본의 `met` 경로가 남아 있다

- 위치: `eval/d4_eval/document_list.py:23-38`, `eval/d4_eval/official_d4.py:200-215,218-244`, `tests/test_document_list.py:32-42,81-94`, `docs/EVAL_CONTRACT_D5.ko.md:25,37-42,123`
- 문제:
  - 중복 `key`·순번·고유번호·PDF 이름·입력 해시와 스캔 조건 검사는 추가되어 중복 목록 반례는 닫혔다.
  - 그러나 완전성의 기준인 `expected_documents`가 검사 대상 JSON 안에만 있다. 사용자 결정이 10개여도 목록을 1개로 줄이면서 `expected_documents`도 1로 바꾸면 실행기·위치 검사·집계가 모두 이를 완전한 목록으로 받아들인다.
  - 집계의 `expected_calls`도 이 자기 선언에서 나오므로 한 호출이 모두 0이면 `met`이다. 새 시험은 `count=1, expected=3`은 거부하지만 `count=1, expected=1`이 계약의 확정 수와 다른 경우를 시험하지 않는다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  from tests.test_document_list import listing
  from eval.d4_eval.document_list import check_document_list
  from eval.d4_eval.official_d4 import bundle, CRITERIA
  one = listing(count=1, expected=1)
  print(check_document_list(one))
  print(bundle([{"name":"01.text.ai", "key":"01", "official_ready":True}],
               CRITERIA["3.1"], 1)["verdict"])
  PY
  ```

  결과는 차례로 `1`, `met`이었다.
- 가장 작은 수정:
  - ③에서 정한 수를 ④의 고정 기록 같은 **목록 밖의 등록된 값**으로 남긴다.
  - 실행기·위치 검사·공식 집계가 그 외부 값을 받아 `expected_documents`, 실제 목록 길이, 호출 수가 모두 같은지 검사한다. D5에서는 목록 안의 값만으로 판정하지 않는다.
  - `계약/고정 값=10, 목록의 expected_documents=9, 실제 9개`와 `=1, 실제 1개`를 모두 거부하는 회귀 시험을 추가한다.

### 2. [중요] “저장소 안 경로”와 D4 자기 목록 예외를 심볼릭 링크로 우회할 수 있다

- 위치: `eval/d4_eval/document_list.py:18-20,23-28,47-64`, `eval/d4_eval/run_d4.py:120-123`, `eval/d4_eval/position_check.py:302-306`, `eval/d4_eval/official_d4.py:218-222,267-273`, `eval/d4_preflight.py:93-115,139-141`
- 문제:
  - `_relative()`는 문자열이 상대경로이고 `..`가 없는지만 본다. 저장소 안의 상대경로가 저장소 밖 파일을 가리키는 심볼릭 링크여도 통과한다.
  - 등록 기록은 그 경우 링크가 가리키는 파일 내용이 아니라 git의 링크 객체만 고정한다. 링크 밖의 문서 목록·정답·매핑표·스캔 대응표 내용이 R 뒤에 바뀌어도 깨끗한 트리와 등록 객체 대조는 그대로 통과할 수 있다.
  - `is_d4_list()`는 `resolve()`로 링크를 따라간다. 따라서 `eval/d5_eval/documents.json`을 D4 목록으로 향한 링크로 만들면 “D4 자기 파일일 때만 10”이라는 예외가 D5 경로에도 적용된다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  import tempfile
  from pathlib import Path
  from eval.d4_eval.document_list import _relative, is_d4_list
  with tempfile.TemporaryDirectory() as t, tempfile.TemporaryDirectory() as outside:
      root = Path(t)
      link = root / "eval/d5_eval/gold/link.json"
      link.parent.mkdir(parents=True)
      link.symlink_to(Path(outside) / "gold.json")
      print(_relative("eval/d5_eval/gold/link.json"))
      print(link.resolve().is_relative_to(root.resolve()))
      d4 = root / "eval/d4_eval/documents.json"
      d4.parent.mkdir(parents=True)
      d4.write_text("{}")
      d5 = root / "eval/d5_eval/documents.json"
      d5.symlink_to(d4)
      print(is_d4_list(d5, root))
  PY
  ```

  결과는 `True`, `False`, `True`였다. 즉 문법상 상대경로 검사는 통과하지만 실제 대상은 저장소 밖이고, D5 링크가 D4 목록으로 판정된다.
- `repo_paths=False` 두 곳의 판단:
  - 공식 집계만 놓고 보면 진짜 실행기가 만든 폴더에서는 독립적인 일부 표본 우회가 아니다. 실행기는 `repo_paths=True`로 같은 목록을 검사하고, 집계는 `run.json`의 `documents_sha256`을 현재 목록과 대조한다.
  - 위치 검사의 절대경로 목록도 그대로는 실행기에서 거부되므로 독립적인 `met` 경로는 아니다.
  - 다만 두 곳 모두 계약과 함수 설명보다 약한 검사를 하며, 손으로 만든 실행 기록이나 등록 전 위치 파일의 신뢰 경계를 넓힌다. 더 중요한 실제 허점은 위 심볼릭 링크로, 이는 `repo_paths=True`인 실행기도 통과한다.
- 가장 작은 수정:
  - 문서 목록 파일 자체와 목록이 가리키는 정답·매핑표·스캔 대응표·등록 자리 파일을 모두 `lstat`으로 확인해 심볼릭 링크가 아닌 일반 파일이고, `resolve()` 결과가 `ROOT` 아래인지 검사한다.
  - 등록 도구도 등록 경로의 심볼릭 링크를 거부하거나, 따라간 실제 내용의 해시를 별도로 고정한다.
  - `position_check.py`와 `official_d4.py`의 제품 경로에서는 `repo_paths=False`를 없앤다. 임시 절대경로가 필요한 단위 시험은 검사 루트를 주입한다.
  - `is_d4_list()`는 링크를 따라간 동일성으로 예외를 주지 말고, 정규화한 실제 인자 경로가 등록된 D4 경로이며 일반 파일일 때만 예외를 준다. D5→D4 링크 거부 시험을 추가한다.

### 3. [중요] D5의 필수 도구 집합과 태그 이름이 고정·등록 기록에 결합되지 않았다

- 위치: `eval/d4_preflight.py:80-90,93-124,139-164,184-218`, `tests/test_d4_tools.py:805-835`, `docs/EVAL_CONTRACT_D5.ko.md:21-22,29,33-36,46-55,69`
- 문제:
  - `--tool-paths`는 받은 목록을 그대로 기록하며 D5의 필수 9개와 같은지 검사하지 않는다. 한 파일만 주어도 유효한 고정 기록이 되고, 이후 점검은 그 한 파일만 충실히 대조한다. 새 시험은 “기록한 추가 파일이 나중에 바뀌면 실패”만 확인하고 “D5 필수 파일을 빼면 고정 자체가 실패”는 확인하지 않는다.
  - 계약은 ④의 실행 가능한 전체 명령을 아직 적지 않고 “위 9개”라고만 한다. 정확한 명령을 담을 절차서는 ⑥ 전 작성이라 ④보다 늦을 수도 있다.
  - `register --tag`는 안내 문구에만 쓰이고 등록 JSON에는 저장되지 않는다. `check`의 `--registered`와 `--tag`도 서로 같거나 등록 기록의 값인지 검사하지 않는다. 로컬 `d5-registered`와 원격 `d4-registered`가 같은 HEAD를 가리키면 서로 다른 이름이어도 점검은 통과한다.
- 근거 명령과 결과:

  ```bash
  python3 - <<'PY'
  from pathlib import Path
  from eval.d4_preflight import freeze_record, TOOL_PATHS, register_record
  record = freeze_record(Path('.'), '180e621', 'HEAD', {}, ('eval/d4_gold.py',))
  print(len(TOOL_PATHS), len(record['objects']['tools']))
  registration = register_record(Path('.'), 'eval/freeze_d4.json', ['docs/EVAL_CONTRACT_D4.ko.md'])
  print('tag' in registration)
  PY
  ```

  결과는 기본 D4 도구 `5`, 받아들인 지정 도구 `1`, 등록 기록의 태그 필드 `False`였다. 임시 로컬 원격에서 `registered='d5-registered'`, `tag='d4-registered'`로 서로 다르게 호출한 `check()`도 `ok: true`, 실패 항목 0개였다.
- 가장 작은 수정:
  - D4 기본값은 그대로 두고, D5용 명명된 프로필 하나에 제품 P `180e621`, 필수 도구 9개, 태그 `d5-registered`, 1번의 확정 문서 수를 묶는다.
  - 고정 기록에 프로필·필수 집합을 저장하고 누락·추가를 거부한다. 등록 기록에는 태그를 저장하고, 점검은 등록 기록에서 태그를 읽거나 `--registered`·`--tag`가 그 값과 모두 같은지 검사한다.
  - ④의 정확한 D5 고정 명령을 계약에 지금 적는다. 필수 도구 하나 누락, D4/D5 태그 혼용을 거부하는 시험을 추가한다.

## 계약에 적을 것

### 4. [사소] DSR 재현 코드를 움직이지 않는 객체로 가리킨다는 약속이 아직 이행되지 않았다

- 위치: `docs/EVAL_CONTRACT_D5.ko.md:70-79`, `docs/reviews/D5_contract_codex_response.ko.md:44,52`
- 문제:
  - DSR 비교 기준은 `label_key`·기간·인쇄값으로 바로잡혔다.
  - 그러나 계약은 “`d5-tools` 브랜치의 최종 커밋을 응답 문서에 적는다”고 하고, 응답은 “이 응답의 커밋 해시(아래)”라고 하지만 실제 해시는 아래에 없다. 같은 커밋이 자기 해시를 내용에 넣을 수 없으므로 현재 문구대로는 이행할 수도 없다.
- 근거 명령과 결과:

  ```bash
  git log --oneline 1547a2c..HEAD
  rg -n '09c0e44|4bf93e1|최종 커밋|커밋 해시' \
    docs/EVAL_CONTRACT_D5.ko.md docs/reviews/D5_contract_codex_response.ko.md
  ```

  도구·계약 수정 커밋은 `09c0e44`이고 그 뒤 `4bf93e1`은 재검토 요청만 추가했지만, 두 문서에는 어느 해시도 기록돼 있지 않다.
- 가장 작은 수정: 후속 커밋에서 응답과 계약에 검증한 코드 객체 `09c0e4430f771ad35a9ccb57cb400516861f3a50` 또는 ④에서 정해질 최종 T 전체 해시를 적는다. “이 응답과 같은 커밋/아래”라는 자기참조 문구는 없앤다.

그 밖에 계약 2판의 파일 배치, 제품 P의 닫힌 범위, 후보 기록 복사 규칙에서 새로 적어야 할 필수 공백은 찾지 못했다. `5cdb4e1`은 `180e621`의 부모이고, `180e621..HEAD`에서 `dart_review/`와 `pyproject.toml`의 차이는 없었다. 20~30번 복사 시 원본 경로·git 객체·받은 시각을 남기고 새 첨부 이름은 D5 파일에만 적는 규칙도 1차 5번을 닫는다. 다만 ⑦~⑨의 파일 전부와 완전한 명령은 약속대로 `docs/D5_RUN_PROCEDURE.ko.md`의 등록 전 검토에서 다시 확인해야 한다.

## 점 날짜와 D4 재현 확인

### 점 날짜

- `DOTTED_PERIOD`는 `^...$`이고 `dated()`가 점 날짜에 이를 쓰므로, 1차 반례인 `2025.12.31 현재 보증금 47`과 `2025.12.31 현재 계약조건을 검토했다`는 기간 줄이 아니었다. 설명문으로 재무제표가 시작되거나 해당 행이 `drop`되는 경로는 닫혔다.
- 실제 글자 층에서 나올 수 있는 다음 변형은 현재 받지 않는다.
  - `제 62 기 2025.12.31 현재 (단위 : 원)`처럼 같은 줄에 단위가 붙은 경우
  - 당기·전기 날짜가 한 글자 줄에 함께 놓인 경우
  - `2025.01.01 ~ 2025.12.31`처럼 물결표로 범위를 쓴 경우
- 이 누락은 CFS OpenDART 항목이 있는 한 거짓 충족으로 이어지지 않는다. 손제작 BS 항목으로 첫 번째 변형을 넣었을 때 재무제표 0개, `statement_not_found/BS` 1개가 생겼다. 이 항목은 `ignore`할 수 없고 `add_statement`·`same_statement`·`unscorable` 중 하나로 사람에게 넘어간다. 따라서 넓혀 받을지는 자동화 범위의 선택이며 고정 차단 사유로 추가하지 않았다. 계약에는 D4 그대로인 한글 날짜 규칙과 새 점 날짜 규칙의 범위가 이미 구분돼 있다.

### D4 정답 10개와 저장 결과

허용된 D4 PDF와 로컬 캐시만 사용해 `eval/d4_gold.py`의 `build()`를 다시 실행했다.

- DSR 이외 9개는 현재 생성 결과의 JSON 바이트가 저장된 `.gold.json`과 모두 같았다.
- DSR은 `연결재무상태표@7`, `연결손익계산서@9`, `연결포괄손익계산서@10`, `연결현금흐름표@12`를 찾았다. 자동 211칸과 수동 212칸을 `(statement_id, page, label_key(label), period, printed)` 다중집합으로 비교하면 교집합 211, 자동 쪽만 0, 수동 쪽만 1이었다. 남은 것은 8쪽 이익잉여금 당기 `219,722,694,808`이었다.
- D4 위치 검사는 `the same: 66 places of 10 documents`였다.
- 기본 경로와 명시적 D4 경로로 저장 보고서를 재집계한 결과는 둘 다 다음과 같았다.

  | 묶음 | 결과 |
  |---|---|
  | 규칙 텍스트 | `not met`, S1 0, L1 0, S2 1, 10호출 |
  | 규칙 스캔 | `not met`, S1 3, L1 2, S2 6652, 30호출 |
  | AI 텍스트 | `not met`, S1 11, L1 4, S2 0, 10호출 |
  | AI 스캔 | `not met`, S1 27, L1 0, S2 5559, 30호출 |

- 관련 단위 시험 84개가 통과했다. 실행기 시험은 제품 호출을 가짜로 바꾼 시험이며 실제 `run_d4.py` 실행은 하지 않았다.
- `git diff 1547a2c..HEAD -- docs/EVAL_CONTRACT_D4.ko.md eval/d4_eval/results/2026-10-20`과 `git diff 180e621..HEAD -- dart_review pyproject.toml`은 모두 비어 있었다. D4의 기본 도구 목록 5개와 기본 태그 `d4-registered`도 유지됐다.

따라서 이번 수정으로 확인된 D4 기본 결과 변화는 없다. 위 재집계 수치는 HEAD 도구의 재집계이고, 계약이 말하듯 D4 공식 결과 자체는 R `1f7b6bf`의 도구로 낸 기록이다.
