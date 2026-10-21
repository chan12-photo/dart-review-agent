# D5 계약·도구 Codex 4차 확인 검토 결과

- 검토일: 2026-10-21
- 대상: `git diff cbe7cbd..HEAD`, 3차 결과와 응답, `docs/EVAL_CONTRACT_D5.ko.md` 초안 4판
- 제약: 인증키·OpenDART·Ollama·네트워크를 쓰지 않았다. 제품 추출, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행은 어떤 PDF에도 하지 않았다. 임시 파일과 임시 Git 저장소는 `/tmp` 아래에만 만들었다.

## 결론

3차의 네 반례 자체는 다음과 같이 고쳐졌다.

1. F에서 N=10을 고정한 뒤 N과 목록을 1로 줄인 반례는 등록에서 거부됐고, 등록 기록을 손으로 만들어도 점검의 F 항목이 실패했다. 로컬 `d5-frozen`만 F의 자손이나 비조상 커밋으로 옮겨서는 등록·점검을 통과하지 못했다.
2. 저장소 밖을 가리키는 등록 기록 링크는 CLI가 쓰기 전에 거부하고 `regular_at_head`도 거부했다. 고정 기록 링크도 같은 두 관문에서 거부됐다.
3. D4 재집계 JSON의 최상위 키는 `official.final2.json`과 같았다. 기존 D4 고정·등록 기록과 프로필 필드가 없는 기존 점검 로그도 현재 기본 동작에서 받아들여졌다.
4. 계약 2절의 ④·⑦·⑧ 명령은 코드의 필수 인자 및 자리와 맞는다.

그러나 **중요 1건**이 남았다. `register_record()`는 등록 시점의 HEAD가 F의 자손인지 검사하지 않고, `check()`는 등록 기록에 이미 있는 `based_on`을 전혀 검사하지 않는다. 그래서 후보 자료가 든 F 밖의 가지에서 등록한 뒤 R을 그 가지와 F의 병합 커밋으로 만들면, 원격 `d5-frozen`을 옮기지 않고도 최종 점검이 모두 통과한다. 이는 계약의 ④→⑤→⑦ 순서를 Git 기록으로 거짓 충족하는 새 경로다.

## 고정 전에 반드시 고칠 것

### 1. [중요] F 밖에서 등록한 뒤 F를 R의 두 번째 부모로 병합하면 전 점검이 통과한다

- 위치:
  - `eval/d4_preflight.py:176-184,201-203`
  - `eval/d4_preflight.py:235-247`
  - `docs/EVAL_CONTRACT_D5.ko.md:16-18,41-53`
- 문제:
  - `register_record(..., remote)`는 로컬·원격 `d5-frozen`이 같은 F인지, F와 HEAD의 고정 기록 객체가 같은지만 본다. F가 현재 HEAD의 조상인지는 등록 때 보지 않는다.
  - 등록 기록에는 등록 직전 HEAD가 `based_on`으로 들어가지만, `check()`는 이 필드를 읽지 않는다.
  - `check()`는 F가 최종 HEAD인 R의 조상인지만 본다. 따라서 F와 무관한 가지 SIDE에 후보·목록·정답을 두고 등록한 다음, `R = merge(SIDE, F)`로 만들면 F가 R의 조상이 된다. SIDE 자체는 F의 자손이 아니어도 된다.
  - 이 경로에서는 원격 `d5-frozen`을 삭제하거나 다시 달 필요가 없다. 후보 자료와 고정 기록을 먼저 SIDE에 만든 뒤 같은 고정 기록 객체만 담은 F를 별도 가지에서 만들고 push하는 순서도 최종 기록만으로는 구별하지 못한다.
- 근거(명령과 결과):

  `/tmp`의 임시 저장소와 로컬 bare `origin`에서 F와 SIDE가 같은 `eval/freeze_d5.json` 객체를 가지되 서로 조상 관계가 없게 만들었다. 이 시나리오 동안 로컬과 원격 `d5-frozen`은 계속 F를 가리켰다. 핵심 명령과 함수 호출은 다음 순서였다.

  ```bash
  SIDE=$(git commit-tree "$H^{tree}" -p "$F^" -m side)
  # SIDE에서 register_record(root, ..., "d5", "origin") 호출
  R=$(git commit-tree "$REGISTERED_TREE" -p "$SIDE" -p "$F" -m R)
  # d5-registered를 R에 달아 push하고 check(..., "origin", "d5") 호출
  ```

  ```text
  nonancestor_register_passed= True
  side_descends_from_f= False
  merge_makes_f_ancestor= True
  registration_based_on_is_first_parent= True
  merge_r_check_ok= True
  merge_r_failed= []
  ```

  즉 등록 직전 커밋인 `based_on`이 F의 자손이 아닌 사실이 기록돼 있는데도 최종 점검은 통과했다.
- 가장 작은 수정:
  - D5 `register_record()`에서 F가 등록 시점 HEAD의 조상인지 확인하고 아니면 등록을 거부한다.
  - D5 `check()`에서 등록 기록의 `based_on`을 다시 검증한다. 최소한 F가 `based_on`의 조상이고, `based_on`이 R의 조상이며, 등록된 각 객체가 `based_on`에서도 기록값과 같은지 확인해야 한다. 그래야 손으로 `based_on`만 바꾼 기록도 통과하지 않는다.
  - F와 같은 고정 기록 객체를 가진 비조상 SIDE에서는 등록이 실패하고, SIDE와 F를 병합해 만든 R도 점검이 실패하는 회귀 시험을 추가한다.

## 계약에 적을 것

독립적인 계약 전용 지적은 없다. 다만 위 1번을 고치면서 2절 ⑦·⑧에 다음 사실을 명시해야 한다.

- 등록 시점의 HEAD가 F의 자손이어야 한다.
- 등록 기록의 `based_on`도 F의 자손이고 R의 조상이어야 하며, 등록 객체들은 `based_on`에서 이미 그 기록값이어야 한다.

이 문구와 검사를 추가하기 전에는 계약 1절의 ④→⑤→⑦ 순서가 코드로 보장된다고 볼 수 없다.

## 3차 반례 재확인

### F의 N과 태그

정확히 N=10인 F를 만들고 10개 목록을 커밋한 뒤, F와 R 사이에서 고정 기록의 N과 목록을 모두 1로 줄였다.

```text
normal_check_ok= True
n10_to_n1_register= refused: eval/freeze_d5.json at HEAD is not the record frozen at F ... (d5-frozen)
n10_to_n1_check_ok= False
n10_to_n1_target_failed= True
```

정상 R에서 로컬 `d5-frozen`만 F의 자손 커밋으로 옮기자 등록은 `origin`의 태그와 다르다는 이유로 거부됐고, 점검은 등록 기록의 F 불일치와 원격 태그 불일치로 실패했다. 비조상 커밋으로 옮기면 F 조상 검사도 추가로 실패했다.

```text
retag_descendant_register= refused: the tag d5-frozen on origin does not name ...
retag_descendant_check_ok= False
retag_nonancestor_check_ok= False
retag_nonancestor_ancestor_failed= True
```

로컬과 원격 태그 자체를 함께 지우고 다른 커밋에 다시 다는 경우는 이미 알려진 원격 권한 한계다. 위 1번은 그 권한을 쓰지 않고 통과하므로 별개의 문제다.

### 고정·등록 기록 링크

등록 기록을 저장소 밖 파일로 가는 링크로 커밋한 상태에서 계약의 `register` CLI를 실행했다. 링크 대상의 해시는 실행 전후 같았다. 같은 HEAD에 `regular_at_head()`와 `check()`를 적용했다.

```text
linked_register_cli_exit= 2
linked_register_cli_refused= True
linked_register_target_unchanged= True
linked_register_regular_at_head= False
linked_register_check_ok= False
linked_register_target_failed= True
```

고정 기록을 저장소 밖 파일로 가는 링크로 바꾼 경우도 같았다.

```text
linked_freeze_cli_exit= 2
linked_freeze_cli_refused= True
linked_freeze_regular_at_head= False
```

따라서 3차의 등록 기록 링크 반례와 그 대칭인 고정 기록 링크는 닫혔다.

### D4 형식과 기존 기록

현재 `official_d4.py`로 저장된 D4 보고서를 `/tmp`에 다시 집계해 `official.final2.json`과 최상위 키를 비교했다.

```text
official.final2.json:
['run_folder', 'judgment_files_not_read', 'run', 'documents_sha256',
 'places_sha256', 'product_reader', 'readers', 'calls']

HEAD 재집계:
['run_folder', 'judgment_files_not_read', 'run', 'documents_sha256',
 'places_sha256', 'product_reader', 'readers', 'calls']

keys_equal= True
```

`cbe7cbd`와 HEAD의 기본 D4 재집계를 직접 비교하면 `cbe7cbd`에만 `expected_documents: 10`이 있었고, 그 필드를 제외한 전체 내용은 같았다. 즉 이번 수정은 3차가 지적한 추가 키만 제거했고 다른 D4 재집계 내용은 바꾸지 않았다.

`d4-registered`를 checkout한 `/tmp` 복제본에서 기존 고정·등록 기록을 현재 `check()`에 넣고, 저장된 기존 점검 로그를 `/tmp`로 복사해 현재 `preflight_passed(..., profile="d4")`에 넣었다.

```text
d4_check_ok= True
failed= []
legacy_log_profile= None
legacy_log_accepted= True
```

따라서 D4 기존 고정·등록 기록과 프로필 필드가 없는 기존 점검 로그는 그대로 받아들여졌다.

### 계약 4판의 명령

- ④의 `freeze --profile d5 --documents-count N --product 180e621 --tools T --out eval/freeze_d5.json`은 프로필의 P·도구 9개·N·고정 기록 자리를 쓰는 코드와 맞는다.
- ⑦의 `register ... --out eval/register_d5.json --remote origin`은 D5에서 `--remote`를 필수로 요구하고 고정·등록 기록 자리를 검사하는 CLI와 맞는다.
- ⑧의 `check` 명령은 D5 등록 태그와 `--remote`를 요구하는 CLI와 맞고, 실행 명령에는 `run_d4.py`의 필수 인자 다섯 개가 모두 있다.
- F의 기록 객체, 로컬·원격 태그, 최종 R에 대한 조상 검사는 계약 문구와 맞는다. 다만 등록 시점의 조상 관계와 `based_on`이 빠져 위 1번이 남았다.

## 시험

관련 시험을 다음과 같이 실행했다.

```bash
TMPDIR=/tmp python3 -m unittest \
  tests.test_document_list \
  tests.test_d4_official \
  tests.test_d4_position \
  tests.test_d4_run \
  tests.test_d4_tools
```

결과는 **145개 실행, 4개 건너뜀, 나머지 141개 통과**였다. 실행기 시험은 임시 입력과 가짜 채점기 응답을 쓰는 단위 시험이며 제품이나 실제 PDF 실행은 하지 않았다. 위 비조상 SIDE→병합 R 반례는 현재 시험에 없다.
