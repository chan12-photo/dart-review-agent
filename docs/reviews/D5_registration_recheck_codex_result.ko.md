# D5 평가 등록 전 Codex 재확인 결과

- 검토일: 2026-10-21
- 범위: `git diff 4069799..HEAD` 중 앞 검토 5건에 대한 수정
- 제한 준수: 인증키·OpenDART API·Ollama·네트워크를 쓰지 않았다. 제품 `python -m dart_review extract`, `eval/d4_score.py --pdf`, `run_d4.py`는 어떤 PDF에도 실행하지 않았다. `~/Desktop/D5/`는 읽기만 했다.

## 결론

**현재 상태로는 등록을 보류해야 한다.** 앞 검토 2~5번은 닫혔고, 1번의 붙은 두 금액 반례와 메모 7개도 고쳐졌다. 그러나 1번 수정이 정답 생성기가 인정하는 `△` 음수 표기를 놓치는 새 문제를 만들었다. 등록 전에 고칠 것은 이 중요 1건이다.

145개 결정과 추가·제거 칸은 전과 같고, 매핑 적용 뒤 인쇄 정답은 2,270칸이며 `unscorable`은 없다. 별도로 기록할 새 사항은 없다.

## 등록 전에 반드시 고칠 것

### 1. 금액 단어 검사에서 `△` 음수 부호를 제거하지 않는다

- **심각도:** 중요
- **위치:** `eval/d5_eval/draft_mappings.py:83-87` (`_printed_on`)
- **근거(명령과 결과):** 변경 전 경계식, 변경 뒤 `_printed_on`, 정답 생성기의 금액 토큰 규칙을 같은 합성 단어로 비교했다.

  ```bash
  .venv/bin/python - <<'PY'
  import re
  from eval.d4_gold import GROUPED
  from eval.d5_eval.draft_mappings import _printed_on
  word = '△1,210'; form = '1,210'
  old = re.search(r'(?<![\d,])' + re.escape(form) + r'(?![\d,])', '손실' + word) is not None
  print('gold amount token', bool(GROUPED.fullmatch(word)))
  print('before change', old)
  print('after change', _printed_on({'words': [{'text': word}]}, form))
  PY
  ```

  ```text
  gold amount token True
  before change True
  after change False
  ```

  `d4_gold.GROUPED`는 `△1,210`을 유효한 음수 금액으로 읽고, 변경 전 검사도 그 안의 `1,210`을 찾았다. 새 검사는 앞의 `(`, `-`, `−`만 떼므로 같은 금액을 “인쇄 없음”으로 잘못 분류할 수 있다. 현재 D5 정답·매핑에는 `△` 인쇄값이 없어 이번 145개 결정에는 영향이 없지만, 붙은 금액을 고치면서 생긴 회귀다.
- **가장 작은 수정:** 앞 부호 제거 문자 집합에 `△`를 넣는다.

  ```python
  re.sub(r"^[(\-−△]+|[)]+$", "", word["text"])
  ```

  수정 뒤 `1,210 707`의 두 금액과 `△1,210`을 모두 찾는 합성 확인을 하고, 아래의 145개 결정·2,270칸 불변 검사를 다시 통과시킨다.

## 기록할 것

**새로 기록할 것은 없다.** 앞 검토 3~5번의 기록은 계약과 후보 메모에 맞게 반영됐다.

## 앞 검토 5건의 확인

### 1. 붙은 두 금액과 바뀐 메모 7개

PDF 10개의 `lines_of` 결과로 `decide`를 메모리에서 다시 계산하고, `4069799`의 매핑과 현재 매핑을 `apply_mapping` 전후로 비교했다. 파일은 쓰지 않았다.

```text
decisions 145
semantic decisions/cells unchanged True
applied gold unchanged True
recomputed decisions+notes match files True
changed notes 7 20_01867758:n5, 20_01867758:n6, 26_01101041:n3, 26_01101041:n4,
                28_01160363:n3, 31_00106881:n1, 31_00106881:n2
printed gold cells 2270 unscorable none
ignore classes 42 22 2
joined amounts True True
```

7개 메모가 가리키는 실제 인쇄 줄과 기존 정답 칸도 다시 맞췄다.

```text
20 n5·n6  12쪽 계속사업 기본 및 희석 주당순이익 1,210 707
26 n3·n4   7쪽 1.자본금 22 2,663,671,300 2,663,671,300
28 n3     11쪽 순확정급여제도의 재측정요소 17,18 3,511,370,550 (4,171,697,637)
31 n1·n2   7쪽 자 본 총 계 37,928,403,107 37,860,333,783
```

따라서 앞 반례와 현재 자료의 메모는 닫혔다. 다만 위의 `△` 회귀 때문에 1번 전체는 아직 등록 가능한 상태가 아니다.

### 2. 감긴 계정명 대체 경로

```bash
.venv/bin/python eval/d5_eval/build_places.py \
  --pdf-dir ~/Desktop/D5 --check eval/d5_eval/duplicate_places.json
```

```text
the same: 49 places (2 by the wrapped-label fallback)
```

합성 입력도 다시 확인했다.

```text
1/100/200: ValueError ... gold cells without a printed row
outside two places: ValueError synthetic: 0 printed lines of that label
allowlist: 2 ['연결재무상태표@8|기타포괄손익-공정가치측정금융자산|0',
              '연결재무상태표@8|기타포괄손익-공정가치측정금융자산|1']
```

대체 경로는 정확한 두 자리만 허용하고, 1·100·200pt의 세 줄과 허용 목록 밖 자리는 멈춘다. 앞 검토 2번은 닫혔다.

### 3~5. 계약·메모 기록

- 계약 5절과 11.3절, 후보 메모는 34번 뒤 입력 조회·첨부 이름 선확인을 **절차 이탈**로 적고, 35~40번 PDF는 받거나 열지 않았으며 표본은 바뀌지 않았다는 한계까지 구분했다.
- 후보 메모의 100자 미만 재무제표 쪽 5개는 앞 검토의 문서·쪽·글자 수·내용과 같다.
- 계약 2절은 공식 집계가 `position_check.check`를 내부 호출하므로 별도 CLI를 공식 절차에서 반복하지 않고, 별도 명령은 문제 확인용이라고 적었다.

앞 검토 3~5번은 닫혔고, 이 문구 수정에서 새 모순은 찾지 못했다.
