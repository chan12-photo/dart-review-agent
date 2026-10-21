# D5 평가 등록 전 Codex 2차 재확인 결과

- 검토일: 2026-10-21
- 범위: `git diff a2309ad..HEAD`의 `eval/d5_eval/draft_mappings.py` 중 `_printed_on`, 앞 재확인 결과, 응답의 "재확인" 절
- 제한: 인증키·OpenDART API·Ollama·네트워크를 쓰지 않았다. 제품이나 평가 스크립트를 PDF에 실행하지 않았고 `~/Desktop/D5/`도 읽지 않았다.

## 결론

**등록 전에 고칠 것 없음.** `△` 지적은 닫혔고, 이번 수정이 만든 새 문제는 찾지 못했다. 145개 결정과 메모도 그대로다.

## 확인 근거

### `GROUPED`·`SMALL`과 `_printed_on`

- **심각도:** 없음
- **위치:** `eval/d5_eval/draft_mappings.py:83-89`
- **근거(명령과 결과):** 아래 합성 검사는 정답 생성기의 각 정규식이 읽는 괄호 유무 × 부호 4종(없음, `-`, `−`, `△`) × 닫는 괄호 유무의 16개 표기를 모두 비교했다. `GROUPED`와 `SMALL`에서 읽힌 16개를 `_printed_on`도 각각 16개 모두 찾았다. 서로 분리된 `1,210 707`은 두 금액 모두 찾고, 붙은 숫자·문자가 붙은 토큰·쉼표가 잘못된 수는 찾지 않았다.

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
  from eval.d4_gold import GROUPED, SMALL
  from eval.d5_eval.draft_mappings import _printed_on

  for form, rule in [('1,210', GROUPED), ('707', SMALL)]:
      tokens = [f'{left}{sign}{form}{right}'
                for left in ('', '(') for sign in ('', '-', '−', '△') for right in ('', ')')]
      read = [token for token in tokens if rule.fullmatch(token)]
      found = [token for token in read if _printed_on({'words': [{'text': token}]}, form)]
      print('generated', len(tokens), 'read', len(read), 'found', len(found), 'same', read == found)

  line = {'words': [{'text': '1,210'}, {'text': '707'}]}
  print('separate words', _printed_on(line, '1,210'), _printed_on(line, '707'))
  for token, form in [('1,210707', '1,210'), ('A1,210', '1,210'), ('12,10', '1,210')]:
      print('reject', token, not _printed_on({'words': [{'text': token}]}, form))
  PY
  ```

  ```text
  generated 16 read 16 found 16 same True
  generated 16 read 16 found 16 same True
  separate words True True
  reject 1,210707 True
  reject A1,210 True
  reject 12,10 True
  ```

- **가장 작은 수정:** 없음.

### 145개 결정과 메모

- **심각도:** 없음
- **위치:** `eval/d5_eval/gold/*.mapping.json`
- **근거(명령과 결과):** 현재 매핑 10개의 `decisions` 전체와 그 안의 `note`를 `a2309ad`의 같은 JSON과 비교했다.

  ```text
  mapping files 10
  decisions current/base 145 145
  decisions+notes identical True
  notes identical True
  mapping diff exit=0
  ```

  마지막 줄은 다음 명령의 종료 코드다.

  ```bash
  git diff --quiet a2309ad..HEAD -- eval/d5_eval/gold/'*.mapping.json'
  ```

- **가장 작은 수정:** 없음.
