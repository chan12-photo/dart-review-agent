# D5 계약·도구 Codex 3차 재검토 결과

- 검토일: 2026-10-20
- 대상: `git diff 4bf93e1..HEAD`, 재검토 결과와 응답, `docs/EVAL_CONTRACT_D5.ko.md` 초안 3판
- 제약: 인증키·OpenDART 요청·Ollama·네트워크를 쓰지 않았다. 제품 추출, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행은 어떤 PDF에도 하지 않았다. 임시 파일과 임시 Git 저장소는 `/tmp` 아래에만 만들었다.

## 결론

재검토 지적 4건은 모두 닫히지 않았다. **치명 1건, 중요 1건**은 ④ 고정 전에 고쳐야 한다. 계약에는 **사소 2건**을 정리해야 한다.

1. 목록 자체를 1개·9개로 줄여 그 수를 스스로 선언하는 원래 반례는, 고정 기록이 그대로라는 조건에서는 실행기·위치 검사·집계·등록 모두에서 닫혔다. 그러나 ④의 F에서 N=10으로 고정한 뒤 `eval/freeze_d5.json`의 N을 1로 바꾸고 ⑦을 진행하면 등록, `d5-registered` 태그, 원격 태그 점검까지 모두 통과한다. 한 문서 묶음도 다시 `met`이 될 수 있다.
2. 문서 목록, 정답, 매핑표, 스캔 대응표의 파일·폴더 링크와 D5→D4 목록 링크는 거부된다. 그러나 **등록 기록 `eval/register_d5.json` 자체가 저장소 밖 파일을 가리키는 링크인 경우**는 `register`와 `check`가 모두 놓친다. R 뒤에 링크 대상 내용을 바꿔도 작업 트리는 깨끗하고 사전 점검은 계속 통과했다.
3. 정상적인 파일을 쓰는 경로에서는 D5 프로필의 도구 9개, P, 태그, 경로와 실행 로그 프로필이 서로 묶였고 D4/D5 혼용도 거부됐다. 다만 1번의 F→R N 변경과 2번의 등록 기록 링크 때문에 전체 관문은 아직 닫히지 않았다.
4. 계약 4절의 두 커밋 해시와 점 날짜 변형 문구는 코드·기록과 맞는다. 2절의 ④·⑦ 명령과 ⑧의 사전 점검 명령도 코드와 맞지만, ⑧의 `run_d4.py` 명령은 필수 인자 세 개가 빠진 조각이라 “정해진 명령”으로는 실행되지 않는다.

D4의 기존 고정·등록 기록과 사전 점검 로그는 현재 기본 프로필로 그대로 받아들여졌고, 저장 보고서 재집계의 수치와 네 판정도 응답 문서와 같았다. 다만 새 집계 JSON에는 기존 D4 공식 결과에 없던 `expected_documents: 10`이 추가된다. 판정 변화는 아니지만 “기록 형식이 그대로”라는 말의 예외다.

## 고정 전에 반드시 고칠 것

### 1. [치명] ④의 N을 바꾼 뒤 그 바뀐 값을 R로 등록해도 전 관문이 통과한다

- 위치:
  - `eval/d4_eval/document_list.py:63-83,92-105`
  - `eval/d4_preflight.py:120-165,171-225`
  - `eval/d4_eval/run_d4.py:123-140`
  - `eval/d4_eval/position_check.py:302-311`
  - `eval/d4_eval/official_d4.py:200-215,218-246,273-280`
  - `docs/EVAL_CONTRACT_D5.ko.md:36-54`
- 문제:
  - `frozen_count()`는 읽은 고정 기록의 프로필이 현재 코드의 프로필과 같은지만 검사한다. N=10을 N=1로 바꾼 기록도 나머지 필드가 같으면 유효한 D5 프로필이다.
  - `register_record()`는 **현재** `eval/freeze_d5.json`을 읽어 목록을 검사하고, 그 현재 파일의 Git 객체를 등록한다. ④의 F에 있던 고정 기록 객체와 같은지는 검사하지 않는다.
  - `check()`는 R의 등록 기록과 현재 고정 기록이 서로 맞고 `d5-registered`가 R을 가리키는지는 확인하지만, R의 고정 기록이 F의 고정 기록과 같은지는 확인하지 않는다. R 태그는 바뀐 N을 잠글 뿐 원래 N을 복원하지 않는다.
  - 따라서 F에서 10을 정한 뒤 후보를 보면서 N과 목록을 1로 함께 줄이고 R을 만들 수 있다. 실행기·위치 검사·집계는 모두 그 바뀐 외부 N=1을 충실히 읽는다.
  - ⑨가 R 밖에서 실행되는 사실도 이 문제를 막지 않는다. 집계는 실행 기록의 `documents_sha256`과 현재 목록을 대조하지만 F는 보지 않는다. R에서 이미 N=1과 한 문서 목록으로 실행했다면 한 호출을 완전한 묶음으로 받아들인다. 반대로 정상적인 R 뒤에 N만 또는 목록까지 바꾸는 별도 경로는 N/목록 일치와 실행 기록의 목록 해시에서 막혔다. 남은 정확한 틈은 **F와 R 사이**다.
- 근거 명령과 결과:

  `/tmp`의 임시 Git 저장소에서 현재 함수를 직접 호출했다. P와 T를 만든 뒤 `freeze_record(..., "d5", 10)`을 F로 커밋하고, 그 파일의 `profile.expected_documents`만 1로 바꿨다. 한 문서 목록과 등록 파일들을 커밋한 뒤 `register_record(..., "d5")`, R 커밋, 로컬 bare 원격으로 `d5-registered` push, `check(..., remote, "d5")` 순서로 실행했다.

  ```text
  F_N= 10 R_N= 1
  freeze_object_changed= True
  register_profile_tag= d5 d5-registered
  preflight_ok= True failed_checks= 0
  registered_count= ('d5', 1)
  one_call_bundle= met
  ```

  관련 단위 시험은 “현재 고정 기록의 N=10, 목록 1개·9개”를 거부하지만, F의 고정 기록 객체가 R까지 유지되는지는 시험하지 않는다. `tests/test_d4_tools.py:865-981`의 프로필 픽스처도 F 이후 고정 기록을 바꾸지 않는다.
- 가장 작은 수정:
  - ④에서 F를 커밋한 즉시 전용 태그(예: `d5-frozen`)를 달아 원격에 push하고, 그 뒤 후보 문서를 연다.
  - D5의 `register`와 `check`가 로컬·원격 `d5-frozen`의 커밋과 `d5-frozen:eval/freeze_d5.json` 객체를 읽어 현재 고정 기록 객체와 같음을 확인하게 한다. 등록 기록에도 F 커밋과 고정 기록 객체를 적고 `check`가 다시 대조한다.
  - `F의 N=10 → 고정 기록을 N=1 또는 9로 수정 → 목록도 같은 수로 수정`한 경우 `register`와 `check`가 모두 실패하는 회귀 시험을 추가한다. R 태그만으로는 F를 증명할 수 없으므로 F의 외부 고정점이 필요하다.

### 2. [중요] 등록 기록 출력 파일의 심볼릭 링크는 저장소 밖의 가변 기록으로 통과한다

- 위치:
  - `eval/d4_preflight.py:120-165,272-300`
  - `eval/d4_eval/document_list.py:25-44`
  - `docs/EVAL_CONTRACT_D5.ko.md:40-45,53`
- 문제:
  - `register_record()`의 링크 검사는 `freeze_path`와 `--paths`에 든 파일만 대상으로 한다. 출력인 `args.out`, 즉 `eval/register_d5.json`은 검사하지 않는다.
  - D5 CLI의 자리 검사는 `normpath(...absolute())`의 문자열 위치만 비교한다. 그 정확한 자리가 심볼릭 링크인지는 보지 않고, `args.out.write_text()`는 링크 대상을 따라간다.
  - `check`도 `args.register`가 프로필의 문자열 자리인지만 확인하고 곧바로 `read_text()`한다. 등록 기록 자체는 자기 `objects`에 들어갈 수 없으므로 이후 객체 대조에서도 잡히지 않는다.
  - 따라서 `eval/register_d5.json` 링크를 미리 커밋해 둔 깨끗한 트리에서 `register`를 실행하면 저장소 밖 파일에 등록 JSON이 써진다. R을 태그한 뒤 그 밖의 JSON을 바꿔도 Git 상태와 R은 변하지 않고 사전 점검이 통과한다. 계약 2절의 “등록 파일도 링크가 없어야 한다”는 현재 코드와 다르다.
- 근거 명령과 결과:

  `/tmp` 임시 저장소에서 정상 D5 F와 한 문서 목록을 만들고, `eval/register_d5.json`을 `/tmp` 아래 파일로 가는 링크로 먼저 커밋했다. 깨끗한 트리에서 `register_record()`가 만든 JSON을 그 경로에 쓴 뒤 R을 만들고 태그를 로컬 bare 원격에 push했다. R 뒤에 링크 대상 JSON의 `registered_at`만 바꾸고 `check()`를 다시 실행했다.

  ```text
  register_path_inside_without_link= False
  git_mode= 120000
  status_after_external_change= ''
  preflight_before_after= True True
  ```
- 가장 작은 수정:
  - `register`가 기록을 만들기 전과 쓰기 전에 `args.out`이 저장소 안에서 링크 없이 도달하는 프로필의 일반 파일 자리인지 검사한다. 아직 파일이 없을 때도 모든 부모가 링크가 아닌지 검사해야 한다.
  - `check`는 읽기 전에 `args.freeze`와 `args.register`에 같은 검사를 하고, HEAD의 파일 모드도 일반 파일인지 확인한다. D4의 기존 일반 파일은 그대로 통과하게 한다.
  - 이미 커밋된 `eval/register_d5.json` 링크를 출력으로 주는 경우와, R 뒤에 링크 대상을 바꾼 경우를 모두 거부하는 시험을 추가한다.

### 링크의 나머지 범위

원래 재검토 반례는 닫혔다. 임시 저장소에서 `inside()`와 `is_d4_list()`를 직접 확인한 결과는 다음과 같았다.

```text
normal True
absolute False
dotdot False
case_variant True
file_link False
folder_link False
d5_link_is_d4= False
```

- 상대 경로 필드의 절대 경로와 `..`, 저장소 밖 파일 링크, 저장소 밖 폴더 링크, D5 목록 자리의 D4 링크는 거부됐다.
- 대소문자만 다른 `EVAL/...`은 대소문자를 구분하지 않는 파일시스템에서 `inside()` 단독으로는 참이었다. 그러나 D4/D5 목록 자리는 `_same_place()`의 철자 비교가 거부하고, 등록 대상은 Git 객체 경로의 정확한 철자도 있어야 하므로 저장소 밖 파일이나 D4 예외로 이어지는 통과 경로는 만들지 못했다.
- 절대 경로나 `..`가 정규화돼 실제 D4 목록 그 자체를 가리키는 인자는 목록 자리 비교에서 같은 파일로 취급될 수 있다. 이는 D5 파일이나 링크를 D4로 바꾸지 않으며 별도 거짓 충족 경로는 아니다.

## 계약에 적을 것

### 3. [사소] 현재 도구로 만든 D4 공식 결과 JSON에는 새 필드가 하나 생긴다

- 위치:
  - `eval/d4_eval/official_d4.py:251-256`
  - `eval/d4_eval/results/2026-10-20/official.final2.json`
  - `docs/EVAL_CONTRACT_D5.ko.md:79-85`
- 문제:
  - 현재 `official()`은 D4에도 `expected_documents: 10`을 무조건 쓴다.
  - 기존 D4 공식 결과 JSON에는 이 필드가 없다. 판정과 수치는 변하지 않았지만, 현재 도구로 재집계한 출력 스키마는 기존 형식과 바이트 단위로 같지 않다.
- 근거 명령과 결과:

  ```bash
  tmpdir=$(mktemp -d /tmp/d5-review.XXXXXX)
  python3 eval/d4_eval/official_d4.py \
    --run eval/d4_eval/results/2026-10-20/run1 \
    --judgments eval/d4_eval/results/2026-10-20/judgments/run1 \
    --out "$tmpdir/current.json"
  # 기존 결과와 최상위 키 비교
  ```

  ```text
  old_keys= ['run_folder', 'judgment_files_not_read', 'run', 'documents_sha256', 'places_sha256', 'product_reader', 'readers', 'calls']
  new_keys= ['run_folder', 'judgment_files_not_read', 'run', 'documents_sha256', 'places_sha256', 'expected_documents', 'product_reader', 'readers', 'calls']
  only_new= ['expected_documents']
  expected_documents= 10
  ```
- 가장 작은 수정:
  - D4 기록 형식을 정말 그대로 둘 것이면 `d4_legacy`일 때 이 필드를 쓰지 않는다.
  - 필드를 유지할 것이면 계약 4절에 “고정·등록·사전 점검 기록 형식은 그대로이고, HEAD 재집계 JSON에는 완전성 근거로 `expected_documents: 10`이 추가된다”고 예외를 적는다. 기존 공식 결과 파일은 바꾸지 않는다.

### 4. [사소] ⑧의 실행기 명령은 필수 인자가 빠져 실행 가능한 전체 명령이 아니다

- 위치:
  - `docs/EVAL_CONTRACT_D5.ko.md:36-46`
  - `eval/d4_eval/run_d4.py:103-115`
- 문제:
  - 계약은 ④·⑦·⑧의 명령이 정해졌다고 하면서 ⑧에 `run_d4.py --documents ... --preflight ...`만 적었다.
  - 실행기는 `--pdf-dir`, `--scan-dir`, `--out`도 필수로 받는다. 따라서 계약의 문자열은 실행 명령이 아니라 인자 조각이다.
- 근거 명령과 결과:

  ```bash
  python3 eval/d4_eval/run_d4.py \
    --documents eval/d5_eval/documents.json \
    --preflight /tmp/d5.preflight.json
  ```

  ```text
  run_d4.py: error: the following arguments are required: --pdf-dir, --scan-dir, --out
  exit=2
  ```

  이 명령은 인자 파싱에서 끝났고 제품이나 PDF를 실행하지 않았다.
- 가장 작은 수정:
  - 계약 2절의 ⑧에 세 필수 인자를 포함한 전체 실행 명령을 적는다. 전체 명령을 `docs/D5_RUN_PROCEDURE.ko.md`에서만 확정할 계획이면, 계약의 “④·⑦·⑧은 정해져 있다”를 “④·⑦과 ⑧의 사전 점검은 정해져 있고 실행기 전체 명령은 절차서에 적는다”로 고친다.

계약 4절의 해시와 점 날짜 문구에서는 그 밖의 공백을 찾지 못했다.

- `09c0e4430f771ad35a9ccb57cb400516861f3a50`와 `0050149504c76fdf094d2c99e419c3492908cf9b`는 실제 커밋이다.
- `git diff --quiet 09c0e4430f771ad35a9ccb57cb400516861f3a50..HEAD -- eval/d4_gold.py eval/d4_score.py`는 종료값 0이었다.
- `DOTTED_PERIOD`는 줄 전체를 받는 `^...$`이고, `statement_not_found`의 허용 결정은 `add_statement`, `same_statement`, `unscorable`뿐이다. 계약에 적은 세 미지원 변형과 사람에게 넘기는 방식이 코드 및 이미 확인된 재검토 결과와 맞는다.

## D5 프로필과 D4 회귀 확인

### D5 프로필

- `PROFILES["d5"]`에는 목록·위치·고정·등록 자리, `d5-registered`, 도구 9개, P `180e621e21713933484fd830a33ea9a05bd271d4`가 함께 있다.
- `freeze --profile d5`는 다른 P와 N 없음/0/불리언을 거부하고 도구 9개를 기록한다.
- `register --profile d5`는 현재 고정 기록의 N과 목록 수를 대조하고 목록·위치·정답·매핑표·대응표 누락을 거부한다.
- `check --profile d5`는 고정 프로필 전체, 등록 기록의 프로필·태그·고정 기록 경로, 로컬·원격 `d5-registered`, 도구 객체를 확인한다.
- 실행기는 목록에서 얻은 프로필과 사전 점검 로그의 프로필을 비교한다. 프로필 없는 기존 로그는 D4로만 받는다.
- 따라서 정상 파일 경로에서 D4 고정·등록 기록이나 D4 로그를 D5에 섞는 경로는 찾지 못했다. 남은 예외는 위 1·2번이다.

### 시험

```bash
python3 -m unittest \
  tests.test_document_list tests.test_d4_official tests.test_d4_position \
  tests.test_d4_run tests.test_d4_tools
```

결과는 **142개 실행, 4개 건너뜀, 나머지 138개 통과**였다. 실행기 시험은 채점기 호출을 가짜로 바꾼 시험이고 실제 제품이나 PDF를 실행하지 않았다.

### D4 기존 기록과 로그

로컬 저장소를 `/tmp`에 복제해 `d4-registered`를 checkout하고, 현재 기본 함수에 저장된 환경 값을 그대로 넣어 읽기 전용 대조를 했다.

```text
saved_freeze_keys= ['product_commit', 'tools_commit', 'objects', 'environment', 'frozen_at']
regenerated_freeze_keys= ['product_commit', 'tools_commit', 'objects', 'environment', 'frozen_at']
freeze_objects_same= True
saved_register_keys= ['freeze', 'product_commit', 'tools_commit', 'objects', 'based_on', 'registered_at']
regenerated_register_keys= ['freeze', 'product_commit', 'tools_commit', 'objects', 'based_on', 'registered_at']
register_objects_same= True
current_default_check_ok= True failed_checks= 0
legacy_log_profile= None accepted_as_d4= True
```

즉 기존 D4 고정·등록 레코드의 키와 객체 목록은 기본 프로필에서 그대로이고, 프로필 필드가 없는 기존 사전 점검 로그도 D4로 받아들였다. 기존 실제 실행 기록의 `run.json`·`run_log.jsonl`은 수정되지 않았고 현재 실행기의 D4 기본 레코드에도 프로필 필드가 추가되지 않는다.

### D4 저장 보고서 재집계

```bash
python3 eval/d4_eval/official_d4.py \
  --run eval/d4_eval/results/2026-10-20/run1 \
  --judgments eval/d4_eval/results/2026-10-20/judgments/run1
```

```text
rules 3.1: not met (S1_official 0, L1 0, S2 1; 10 calls)
rules 3.3: not met (S1_official 3, L1 2, S2 6652; 30 calls)
ai 3.1: not met (S1_official 11, L1 4, S2 0; 10 calls)
ai 3.3: not met (S1_official 27, L1 0, S2 5559; 30 calls)
```

응답 문서의 재집계 수치와 같고 네 판정은 모두 미충족으로 유지됐다. 이는 HEAD 도구의 재집계이며 D4 공식 결과 자체는 계속 R `1f7b6bf` 도구로 낸 `official.final2.json`이다.

마지막으로 다음 두 대조는 모두 종료값 0이었다.

```bash
git diff --quiet 4bf93e1..HEAD -- docs/EVAL_CONTRACT_D4.ko.md eval/d4_eval/results/2026-10-20
git diff --quiet 180e621e21713933484fd830a33ea9a05bd271d4..HEAD -- dart_review pyproject.toml
```

따라서 D4의 저장된 계약·기록·결과와 제품 P는 바뀌지 않았다. 확인된 D4 쪽 새 변화는 3번의 재집계 JSON 추가 필드 하나다.
