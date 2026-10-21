# D5 계약·도구 Codex 5차 확인 검토 결과

- 검토일: 2026-10-21
- 대상: `git diff 9b53f69..HEAD`, 4차 결과와 응답, `docs/EVAL_CONTRACT_D5.ko.md` 초안 5판
- 범위: 4차의 SIDE→병합 R 반례, 새 D5 점검 항목, 정상 D5 등록 절차, D4 기본 동작만 확인했다.
- 제약: 인증키·OpenDART API·Ollama·네트워크를 쓰지 않았다. 제품 추출, `eval/d4_score.py --pdf`, `run_d4.py`의 실제 실행은 어떤 PDF에도 하지 않았다. 임시 Git 저장소는 `TMPDIR=/tmp`로 만들었다.

## 결론

4차 지적 1건은 닫혔다. F 옆 가지 SIDE에서의 등록은 F가 HEAD의 조상이 아니라는 이유로 거부된다. 등록 기록을 손으로 만들고 `merge(SIDE, F)`를 R로 삼아도 R의 단일 부모 조건과 `F → based_on` 조건이 실패한다.

정상 절차인 등록 → 등록 기록만 커밋해 단일 부모 R 생성은 통과했다. 새 검사는 `profile != "d4"` 분기 안에만 있어 D4 기본 동작을 바꾸지 않았고, 기존 D4 정상 등록 체크아웃도 통과했다.

R의 단일 부모, `based_on`과 R 사이의 변경, F와 `based_on`의 조상 관계, `based_on`에서의 등록 객체 대조에서 이번 반례를 다시 통과시키는 우회는 보이지 않았다.

## 고정 전에 반드시 고칠 것

없다.

## 계약에 적을 것

없다. 초안 5판 2절 ⑦·⑧은 구현된 조건과 맞는다.

## 근거

### 코드와 계약

- `eval/d4_preflight.py:162-188`: D5 등록에서 로컬·원격 F를 확인한 뒤 `git merge-base --is-ancestor F HEAD`가 아니면 등록을 거부한다.
- `eval/d4_preflight.py:224-275`: 새 점검은 D5 분기 안에서만 실행된다. HEAD의 부모가 정확히 `[based_on]`인지, `git diff --name-only based_on HEAD`가 등록 기록 하나인지, F가 `based_on`의 조상인지, 등록 기록의 각 객체가 `based_on`에서도 같은지 검사한다.
- `docs/EVAL_CONTRACT_D5.ko.md:44-59`: 등록 시점 HEAD의 F 자손 조건, 단일 부모 R, 등록 기록만의 변경, `F → based_on`, `based_on` 객체 대조가 코드와 같은 내용으로 적혀 있다.

### 4차 반례와 정상 절차 재실행

다음 명령은 시험마다 `/tmp` 아래에 새 저장소와 로컬 bare 원격을 만들며 실제 PDF나 제품을 실행하지 않는다.

```bash
TMPDIR=/tmp python3 -m unittest -v \
  tests.test_d4_tools.ProfileTests.test_a_registration_beside_f_merged_in_afterwards_is_refused \
  tests.test_d4_tools.ProfileTests.test_the_profile_is_frozen_with_its_nine_tools_and_n \
  tests.test_d4_tools.ProfileTests.test_r_is_exactly_the_registration_commit
```

결과:

```text
test_a_registration_beside_f_merged_in_afterwards_is_refused ... ok
test_the_profile_is_frozen_with_its_nine_tools_and_n ... ok
test_r_is_exactly_the_registration_commit ... ok

Ran 3 tests in 4.215s
OK
```

첫 시험은 4차 반례와 같이 F와 같은 고정 기록 객체를 가진 비조상 SIDE를 만든다. SIDE에서 `register_record()`가 `is not an ancestor of HEAD`로 거부되는지 확인하고, `based_on = SIDE`인 기록과 두 부모 `(SIDE, F)`인 R을 손으로 만들어 다음 두 점검이 실패하는지도 확인한다.

```text
R's only parent is the registered commit, and R adds only the registration record
F (d5-frozen) is an ancestor of the registered commit
```

두 번째 시험의 정상 단일 부모 R은 실패 항목이 없었다. 세 번째 시험에서는 등록 뒤 다른 등록 파일까지 바꾼 커밋이 `based_on`과 R의 변경 조건에서 실패했다.

### D4 기본 동작과 D5 원격 태그 정상 경로

```bash
TMPDIR=/tmp python3 -m unittest -v \
  tests.test_d4_tools.PreflightTests.test_the_registered_checkout_passes \
  tests.test_d4_tools.ProfileTests.test_r_is_named_by_its_tag_and_the_registration_is_the_profile_s
```

결과:

```text
test_the_registered_checkout_passes ... ok
test_r_is_named_by_its_tag_and_the_registration_is_the_profile_s ... ok

Ran 2 tests in 3.775s
OK
```

D4의 기존 등록 체크아웃은 그대로 통과했다. D5도 정상 R에 `d5-registered`를 달아 로컬 bare 원격에 push한 뒤 원격을 포함한 점검에서 실패 항목이 없었다.
