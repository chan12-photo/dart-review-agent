# D4 6차 검토 결과: ④ 고정 전 신뢰 경계 점검

- 검토일: 2026-10-15. 대상: `5175eba..5d8cbd6`, `docs/EVAL_CONTRACT_D4.ko.md` 6판.
- 범위: 요청서의 세 질문만. 인증키·OpenDART API·Ollama·봉인 3-1 평가는 사용하지 않았다. 실제 신규 후보나 새 PDF에서의 발생 빈도는 확인하지 않았다.
- **결론: ④ 고정 전에 고칠 것 1건.** 단위가 확인되지 않은 숫자 표를 계약이 허용한 `ignore`로 처리하면 정답 칸이 0개인데도 공식 판정 가능 상태가 된다. 5차 1·5·6번의 수정 반례는 통과했다.

## ④ 고정 전에 고칠 것

### 1. [치명] `no_unit=ignore`가 숫자 표 전체를 정답에서 빼도 공식 판정이 가능하다

- **위치:** `eval/d4_gold.py:155-159, 300-303, 419-447`; `eval/d4_score.py:160-170, 262-288`; `docs/EVAL_CONTRACT_D4.ko.md:161, 220-241`.
- **근거:** `cells_of()`는 단위가 발견되지 않은 표에서 `no_unit` 매핑 항목을 만들고 칸을 하나도 반환하지 않는다. 계약은 이 항목에 `ignore`를 허용한다. `apply_mapping()`은 `no_grouped_amounts=ignore`와 달리 `no_unit=ignore`를 `unscorable`로 표시하지 않는다. `score()`에는 정답 칸 수가 0인 재무제표를 공식 판정에서 막는 조건이 없다.
- **재현 명령·결과:** `./.venv/bin/python - <<'PY'`로 단위 표기가 없는 합성 연결손익계산서의 인쇄 줄 `매출액 1,000 2,000`과 OpenDART 합성 값 `777/888`을 `build()`에 전달했다. `lines_of`와 `statements_of`만 이 합성 줄·표로 대체했다. `needs_mapping` 세 항목(`no_unit`, `dart_only`, `dart_only`)을 서로 다른 근거로 `ignore`하고, `confirmed` 매핑표와 같은 원본 해시가 적힌 빈 저장 보고서를 `score(..., report_sha256='saved-report-sha')`에 넣었다. 출력은 `{'needs': ['no_unit', 'dart_only', 'dart_only'], 'gold_cells': 0, 'S1': 0, 'L1': 0, 'S2': 0, 'official_ready': True}`였다. 표의 인쇄 숫자를 제품도 놓쳐도 S2가 0이 된다. 해시는 합성값이다. 이 시험은 실제 PDF에서 이 상황이 발생했다는 뜻이 아니다.

  ```sh
  ./.venv/bin/python - <<'PY'
  from pathlib import Path
  from unittest.mock import patch
  from eval.d4_gold import build, apply_mapping
  from eval.d4_score import score
  words = [{'text': t, 'x0': x, 'x1': x + 45, 'top': 100,
            'bottom': 108, 'page_height': 1000}
           for t, x in [('매출액', 10), ('1,000', 310), ('2,000', 510)]]
  line = {'page': 1, 'words': words, 'text': '매출액 1,000 2,000',
          'compact': '매출액1,0002,000', 'top': 100, 'bottom': 108}
  block = {'id': '연결손익계산서@1', 'kind': 'IS', 'title': '연결손익계산서',
           'consolidated': True, 'page': 1, 'end_page': 1,
           'unit_text': None, 'lines': [line]}
  items = {'CFS': [{'sj_div': 'IS', 'account_nm': '다른 묶음',
                    'thstrm_amount': '777', 'frmtrm_amount': '888'}]}
  with patch('eval.d4_gold.lines_of', return_value=[line]), \
       patch('eval.d4_gold.statements_of', return_value=[block]):
      gold = build(Path('synthetic_missing.pdf'), items)
  gold['source']['sha256'] = 'synthetic'
  decisions = {n['id']: {'decision': 'ignore',
                         'note': f"1쪽 {n['why']} {n['id']}: 인쇄 매출액 1,000/2,000; 별도 묶음 777/888 또는 단위 미표기"}
               for n in gold['needs_mapping']}
  mapped = apply_mapping(gold, {'status': 'confirmed', 'confirmed_by': 'reviewer',
                                'confirmed_at': '2026-10-14', 'decisions': decisions})
  result = score(mapped, {'statements': [], 'problems': [],
                          'source_sha256': 'synthetic'}, None, 'saved-report-sha')['totals']
  print({'needs': [n['why'] for n in gold['needs_mapping']],
         'gold_cells': result['gold_cells'], 'S1': result['S1'],
         'L1': result['L1'], 'S2': result['S2'],
         'official_ready': result['status']['official_ready']})
  PY
  ```
- **왜 신뢰 경계 안인가:** 원본에 단위가 없어서 사람이 값을 원 단위로 확정하지 못하는 경우 `no_unit=ignore`는 현재 계약의 허용 결정이다. 별도 묶음의 OpenDART 숫자를 `dart_only=ignore`하는 것도 허용된다. 등록 밖 입력이나 위조 기록이 없어도 생기는 경로다.
- **가장 작은 수정:** `no_unit=ignore`로 숫자가 있는 표를 정답에서 제외하면 `unscorable`에 이유를 넣어 공식 판정을 막는다. `no_grouped_amounts=ignore`와 같은 방식으로 처리하고, 단위 미표기 표의 `add`와 `ignore` 각각을 회귀 시험한다. `add`에는 사람이 확인한 단위와 인쇄 근거를 남긴다. 표를 공식 대상에서 제외한다면 제외 문서 수·이유를 보고한다.

## 5차 1·5·6번 재확인

실행 명령: `./.venv/bin/python -m unittest tests.test_d4_tools.GoldBuilderTests.test_amounts_without_separators_can_be_added_and_scored_and_not_ignored_into_an_empty_gold tests.test_d4_tools.GoldBuilderTests.test_an_added_statement_must_lie_in_the_pdf_and_be_named_by_its_first_page tests.test_d4_tools.CandidateRuleTests.test_select_tells_a_missing_list_from_an_empty_one_and_keeps_the_period` → **3개 통과**. `./.venv/bin/python -m unittest tests.test_d4_tools` → **51개 통과**. 첫 표적 실행에서는 검토자가 시험 클래스 이름을 `CandidateTests`로 잘못 적어 loader 오류 1개가 났고, 실제 이름 `CandidateRuleTests`로 바로잡아 재실행했다.

| 5차 항목 | 현재 반례 결과 | 남은 한계 |
|---|---|---|
| 1. 쉼표 없는 `1000` | `add`가 정답 칸 두 개를 받아 채점 결과 `gold_cells=2, correct=1, missing=1`; `no_grouped_amounts=ignore`는 `unscorable`이며 `scorable=false`. | 위 `no_unit`은 다른 항목이라 별도 결함이다. |
| 5. 추가한 표의 쪽 범위 | 쪽 수 미상·PDF 밖 999쪽·ID와 첫 쪽 불일치·겹침 근거 누락을 거부한다. 쪽 수 안의 3쪽과 겹침 근거가 있는 1쪽은 받는다. | `overlap_note`의 사실성은 사람 검토다. |
| 6. 후보 목록·기간 | `filings` 누락은 `기록 부족`; 2027년 공시는 `out_of_period=['C']`로 남기고 `사업보고서 없음`으로 제외한다. 제외 목록은 별도 인자로 적용한다. | 입력이 실제 `list.json`의 완전한 기록인지는 계약의 운영 절차에 달려 있다. |

## 계약이 코드보다 강하게 읽히는 문장: 기록만 할 것

1. **매핑표 등록 때 확정 상태 검사.** `docs/EVAL_CONTRACT_D4.ko.md:50,65`는 등록 과정이 확정하지 않은 매핑표를 막는다고 읽힌다. 실제 `eval/d4_preflight.py:101-104`는 이름이 `.mapping.json`으로 끝나는 파일만 상태를 검사한다. 임시 Git 저장소에서 `register_record(root, 'freeze.json', ['mapping.json'])`은 `status='draft'` 파일을 **수용**했고, 같은 내용을 `sample.mapping.json`으로 주면 **거부**했다. 공식 채점은 `eval/d4_score.py:279-288`에서 `draft`를 공식 판정 가능으로 만들지 않으므로 위 1번과 같은 지표 왜곡 반례는 아니다. ⑦의 등록 파일명을 `*.mapping.json`으로 고정하거나, 계약 문장에 파일명 조건을 적어 두는 것이 최소한이다.
2. **근거 내용의 기계 검사.** `docs/EVAL_CONTRACT_D4.ko.md:162-166`의 “기계 검사” 아래에는 항목별 쪽·인쇄 줄·계산을 적는다고 되어 있다. `eval/d4_gold.py:386-391`은 `note`가 비지 않고 서로 동일하지 않은지만 확인하며, 그 내용이 실제 쪽·줄·계산과 맞는지는 검사하지 않는다. 사람 확인 절차를 유지하되, 계약에서 이 부분은 사람이 확인한다고 분리해 쓰면 구현과 표현이 맞는다. ④를 막는 자동 채점 결함으로 분류하지 않는다.

## 직접 확인 범위

- 변경 diff, 계약, 5차 결과·응답, D4 정답 생성기·후보 선택기·채점기·사전 점검기와 관련 시험을 읽었다. 합성 함수 반례, 임시 Git 저장소의 등록 파일명 반례, 3개 표적 시험과 D4 도구 시험 51개를 직접 실행했다.
- 실제 새 공시 목록·PDF·확정 매핑표·모델 출력·D4 전체 실행은 확인하지 않았다. 5차에서 범위 밖으로 정한 고의의 등록 외 입력, `same_statement`, `row_unit`, 작은 숫자 경고 등은 이번에 재평가하지 않았다.
- **다음 순서:** 위 `no_unit=ignore` 경로와 회귀 시험을 최소 수정한 다음, 계약 10절 사용자 결정을 받아 ④를 고정한다. 이 보고서는 D4의 실제 정확도나 합격을 판정하지 않는다.
