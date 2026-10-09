# 3-5 보고서·README 검토 결과

- 검토일: 2026-10-09
- 대상: `ebd5fa6..f3f3b64`, 특히 `eval/template_3-5/REPORT.md`, 두 README, P5, 저장된 두 실행과 사람 검토·판정 기록.
- 경계: 인증키·OpenDART API·Ollama를 사용하지 않았다. 3-5 평가와 공식 판정을 다시 실행하거나 바꾸지 않았다. 저장된 기록을 읽고 메모리 안에서 필요한 집계와 채점 민감도만 대조했다.

## 공개 전에 고칠 것

### 1. [중요] “수치 답 419개가 모두 서로 다른 칸”은 원본 근거 칸 기준으로 틀리다

- **위치:** `eval/template_3-5/REPORT.md:32-35`, `README.md:76`, `README.ko.md:76`; 원인인 집계는 `eval/judge.py:377-388`, 계약은 `docs/EVAL_CONTRACT_3-5.ko.md:255-259`.
- **근거:** 판정기의 `distinct_cells_answered`는 원본 응답의 보고서·칸·계정 행을 세지 않는다. `questions[item]["expected"]`에서 회사·기준·계정·질문의 기간·비교 기간을 직렬화해, **질문 조합**의 중복을 센다. 그래서 `figure_answers=419`, `distinct_cells_answered=419`가 나왔다. 반면 정답 파일의 실제 근거 행을 `(response_sha256, column, sj_div, account_id, account_nm, fs_div)`로 묶으면, 정답 제공 419문항이 참조한 근거는 730회이고 서로 다른 근거 행은 **642개**다. 88회는 이미 등장한 행을 다시 참조한다. 예를 들어 A1-001의 조회값과 A7-004의 비교 대상 현재값은 둘 다 NAVER 별도 2024년 말 자산총계, 접수번호 `20250318000645`, `thstrm/BS/ifrs-full_Assets/OFS`, 금액 `17,597,111,016,833`원이다.
- **재현 명령과 결과:**

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  p = Path('eval/template_3-5')
  report = json.loads((p / 'judge_report.json').read_text())
  gold = {x['id']: x for x in json.loads((p / 'gold.json').read_text())['answers']}
  ids = report['outcome_table']['crosscheck']['정답 제공']
  cells = [(v.get('response_sha256'), v.get('column'), v.get('sj_div'),
            v.get('account_id'), v.get('account_nm'), v.get('fs_div'))
           for item in ids for v in gold[item]['values'].values()]
  print(len(ids), len(cells), len(set(cells)))
  PY
  # 419 730 642
  ```

- **영향:** `1 − 0.05^(1/419) = 0.7124%`라는 계산 자체는 계약대로 **419개의 답을 독립 시행으로 가정한 참고값**이다. 하지만 “모두 서로 다른 칸”이라는 설명은 이 가정을 실제보다 강하게 보이게 하며, 계약이 별도로 요구한 근거 칸의 중복 정보도 제공하지 못한다. 642를 새 독립 시행 분모로 쓰라는 뜻은 아니다. 한 답은 여러 행을 쓸 수 있고 행도 반복된다.
- **제안:** 보고서·두 README의 “모두 서로 다른 칸”을 삭제하고, `419개 답 / 근거 행 참조 730회 / 서로 다른 원본 근거 행 642개`처럼 **질문 수와 근거 행 수를 분리**한다. `distinct_cells_answered`의 이름이나 계산도 다음 판정기 버전에서 원본 행 기준으로 바로잡는다. 이 정정으로 저장된 공식 점수·판정을 바꾸지는 않는다.

### 2. [중요] “막은 오답 0”은 실제로 “막은 잘못된 수치 답 0”만 검사한다

- **위치:** `eval/judge.py:443-450`, `eval/template_3-5/REPORT.md:99-103,111-114,162-165`, `README.md:7-13,73`, `README.ko.md:7-13,73`. 계약의 표현은 `docs/EVAL_CONTRACT_3-1.ko.md:184-189`.
- **근거:** 계약은 “막은 오답”을 규칙만 또는 모델만이면 **틀렸을 것**으로 적고, 같은 결과표에 “잘못된 거절”을 별도 실패로 둔다. 그러나 판정기는 비교 대상의 결과가 정확히 `잘못된 수치 답`일 때만 `막은 오답`으로 센다. 규칙만 실행의 잘못된 거절은 4건이며, 교차 확인에서 A2-032·A5-043은 여전히 잘못된 거절, A1-038은 불필요한 되묻기, A8-032는 무응답이 됐다. 즉 교차 확인이 **거짓 “자료 없음” 거절을 두 번 내지 않게 한 것**은 맞지만, 그 두 질문의 정답을 제공한 것은 아니다. 저장된 지표의 0은 “잘못된 **수치** 답을 막은 건수 0”으로 읽어야 한다.
- **재현 명령과 결과:**

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  r = json.loads(Path('eval/template_3-5/judge_report.json').read_text())
  ids = r['outcome_table']['baseline']['잘못된 거절']
  print(ids)
  print([(i, r['outcomes']['crosscheck'][i]) for i in ids])
  print(len(r['crosscheck_effect']['막은 오답']))
  PY
  # ['A1-038', 'A2-032', 'A5-043', 'A8-032']
  # [('A1-038', '불필요한 되묻기'), ('A2-032', '잘못된 거절'),
  #  ('A5-043', '잘못된 거절'), ('A8-032', '보류·무응답')]
  # 0
  ```

- **제안:** 보고서·README에서 `막은 잘못된 수치 답 0`이라고 좁혀 쓰고, 잘못된 거절 두 건이 되묻기·무응답으로 바뀌었으나 **해결되지는 않았다**고 함께 적는다. 이는 LLM의 공로를 새 “정답” 두 건으로 세자는 제안이 아니다.

### 3. [중요] “잃은 정답 62”를 모두 답이 있는 질문처럼 설명한다

- **위치:** `README.md:12-14`, `README.ko.md:12-14`; 관련 수치는 `eval/template_3-5/REPORT.md:99-103`.
- **근거:** 판정기의 `잃은 정답` 62건은 해결한 **답 있는 질문 57건**과 원래 맞게 거절·되물었던 **함정 5건**을 합한 값이다. 다섯 함정은 `B6-002`, `B7-007`, `B7-008`, `B7-010`, `B8-002`다. 그래서 README의 “lost answerable questions” / “답할 수 있는 질문을 잃었다”를 62건 전부의 설명으로 읽으면 분모가 섞인다. 숫자 답 해결률의 차이는 실제로 `476 − 419 = 57`이다.
- **재현 명령과 결과:**

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  r = json.loads(Path('eval/template_3-5/judge_report.json').read_text())
  lost = r['crosscheck_effect']['잃은 정답']
  print(len(lost), sum(x.startswith('A') for x in lost),
        [x for x in lost if x.startswith('B')])
  PY
  # 62 57 ['B6-002', 'B7-007', 'B7-008', 'B7-010', 'B8-002']
  ```

- **제안:** “잃은 정답 62건: 답이 있는 질문 57건, 함정의 올바른 처리 5건”이라고 두 README와 보고서의 효과 설명에 명시한다. 현재 419/480, 476/480 수치는 그대로 둔다.

### 4. [중요] 모델 오독 40건의 원인 분류가 원시 해석과 맞지 않는다

- **위치:** `eval/template_3-5/REPORT.md:115-126`, `README.md:73-77`, `README.ko.md:73-77`.
- **근거:** `cases.jsonl`의 서로 다른 `rule_key`·`model_key` 40건을 해당 질문과 모델 원시 해석으로 다시 분류하면 다음과 같다. 분기말을 3개월로 읽음 **16**, 영어 회사 표기로 바꿈 **14**(`LG Energy Solution` 13 + `LG ENSOL`인 A2-047 1), 연간 흐름을 시점으로 읽음 **4**(A1-011, A1-038, A3-036, A8-046), 연도 자체를 다르게 읽음 **3**(A3-033, A7-040, A8-035), 그룹을 회사로 확정 **2**(B7-007, B7-010), 모호한 “이익”을 한 계정으로 확정 **1**(B6-001)이다. 합계는 40이다. 현행 표의 `16+13+5+4+2=40`은 A2-047과 B6-001을 해당 원인으로 설명하지 못하고, 연간/시점과 연도/기간을 각각 하나씩 과대 계상한다.
- **재현 명령과 결과:**

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  c = {x['id']: x for x in map(json.loads,
       Path('eval/template_3-5/runs/crosscheck/cases.jsonl').read_text().splitlines())}
  diff = [x for x in c.values() if x['readings']['rule_key'] is not None
          and x['readings']['model_key'] is not None
          and x['readings']['rule_key'] != x['readings']['model_key']]
  print('해석 불일치', len(diff))
  print('영어 회사명', [(x['id'], x['readings']['model']['company']) for x in diff
                    if x['readings']['model']['company'] in ('LG Energy Solution', 'LG ENSOL')])
  print('모호한 계정', c['B6-001']['readings']['rule_key'],
        c['B6-001']['readings']['model_key'])
  PY
  # 해석 불일치 40
  # 영어 회사명: LG Energy Solution 13건 및 (A2-047, 'LG ENSOL')
  # 모호한 계정: ['clarify', ...] / ['compare', ..., 'net_income', ...]
  ```

- **제안:** 위 여섯 갈래로 40건 표를 다시 쓰고, 제품 결함의 회사 표기 영향은 “영어 이름 13건”과 “영어 약칭 1건”을 구분하거나 총 14건으로 적는다. B6-001은 최종 되묻기가 맞았지만 **모델 해석 자체는 한 계정으로 성급히 좁혔다**는 점을 남긴다.

### 5. [중요] P5는 점수를 바꾸지 않았지만 공식 판정을 낼 수 있는 조건을 실행 뒤에 바꿨다

- **위치:** `eval/template_3-5/REPORT.md:12,19`, `eval/template_3-5/amendments.json:2-13`, `eval/judge.py:146-171,297-301,398-409`; README 3-5 설명 `README.md:57-77`, `README.ko.md:57-77`.
- **근거:** 규칙만 `run.json`은 실행 커밋 `e1024a2`, 교차 확인은 `6d238db`를 기록한다. 옛 `check_runs`는 서로 다른 커밋이면 `판정 보류`였고, P5가 두 커밋 사이의 차이가 `eval/template_3-5/runs/` 아래일 때 통과시키도록 바꿨다. 따라서 **점수·80%/90% 등의 수치 문턱은 같아도**, 엄격 판정의 **입장 검사**는 바뀌었고, P5가 없었다면 이번 결과는 “기준 충족”이 아니라 “판정 보류”였다. 이번 실제 커밋의 변경 경로는 기준 실행 파일의 추가뿐이다. 두 실행 커밋 각각의 `frozen_differences`는 빈 목록이고, 저장된 판정의 `problems`도 빈 목록이다. 그러므로 현재 기록에서 코드 고정 위반이 발견됐다는 뜻은 아니다.
- **재현 명령과 결과:**

  ```bash
  git diff --name-status e1024a2 6d238db
  # A eval/template_3-5/runs/baseline/{cases.jsonl,human_review.json,review_sheet.md,run.json,summary.json}
  git diff --name-status 6d238db ae82356
  # A eval/template_3-5/runs/crosscheck/{cases.jsonl,human_review.json,review_sheet.md,run.json,summary.json}
  python3 -m unittest tests.test_template_eval.PerRunCommitTests
  # Ran 1 test ... OK
  ```

- **제안:** 보고서의 “점수와 기준은 바뀌지 않는다”를 “점수와 **수치 문턱**은 같으나, 실행 커밋 불일치에 관한 **판정 가능 조건**은 실행 뒤 P5로 완화했다”로 바꾼다. 두 README의 3-5 공식 판정 옆에도 이 사후 절차 수정 사실을 한 문장으로 연결한다. 공식 판정을 임의로 뒤집을 필요는 없지만, 독자는 **사전 등록된 점수 기준**과 **사후 수정된 입장 검사**를 구별할 수 있어야 한다.

### 6. [사소] 한국어 README의 Codex 검토 순서가 영어판·커밋 기록과 반대다

- **위치:** `README.ko.md:62` 대 `README.md:62`.
- **근거:** 한국어는 “사전 등록 뒤 Codex 검토를 받았다”, 영어는 “after a Codex review”라고 썼다. `git log --oneline e1024a2 -3`의 순서는 `e1024a2`(R2 사전 등록) ← `ebd5fa6`(Codex 검토 반영) ← `89c8d3b`(검토 요청)이다. 최종 R2보다 Codex 검토 반영이 먼저다.
- **제안:** 한국어를 “Codex 검토를 반영해 R2를 사전 등록했다”로 고친다.

## 기록만 할 것

### 7. [사소] 무응답 31건의 `body_ok=true`는 본문 기준의 문구와 긴장 관계가 있다

- **위치:** `eval/HUMAN_REVIEW.ko.md:11-27`, `eval/template_3-5/runs/{crosscheck,baseline}/human_review.json` 및 각 `final.json`.
- **근거:** 본문 기준은 필요한 내용을 말하지 않은 짧은 답을 실패로 본다. 그런데 표시된 답이 아예 없는 교차 확인 28건과 규칙만 3건 모두 사람 검토에 `body_ok=true`가 들어 있다. 예를 들어 A1-020의 메모는 “보여 준 본문 없음”이라고 적었다. 이는 **본문 자체의 통과**라기보다는 “추가적인 허위 문장은 없다”는 의미로 쓰인 듯하다. 이 31건은 이미 자동 실패이고 최종 결과가 모두 `보류·무응답`이므로 공식 점수·판정을 유리하게 바꾼 흔적은 없다.
- **재현 명령과 결과:**

  ```bash
  python3 - <<'PY'
  import json
  from pathlib import Path
  p = Path('eval/template_3-5/runs')
  for mode in ('crosscheck', 'baseline'):
      cases = [json.loads(x) for x in (p/mode/'cases.jsonl').read_text().splitlines()]
      final = {x['id']: x for x in json.loads((p/mode/'final.json').read_text())['per_case']}
      print(mode, sum(x['answer'] is None and final[x['id']]['body_ok'] is True for x in cases))
  PY
  # crosscheck 28 / baseline 3
  ```

- **제안:** 기존 기록을 소급 수정하지 말고, 다음 평가의 본문 검토 기준에서 무응답의 `body_ok` 의미를 `false` 또는 “평가 불가”로 정한다. 현재 보고서에는 무응답을 본문 통과 사례로 해석하지 않는다고 명시하면 충분하다.

### 8. [사소] P5의 경로 검사만으로는 모든 실행 기록의 불변성을 증명하지 못한다

- **위치:** `eval/judge.py:146-158`.
- **근거:** `only_run_records_between`은 `git diff --name-only`의 **경로 접두어**만 검사한다. 파일이 새로 추가됐는지, 기존 `cases.jsonl`이나 `run.json`을 수정·삭제했는지는 이 함수 단독으로 구별하지 않는다. 각 실행의 고정 코드 검사는 별도로 수행하지만, 이 함수의 “기록 파일만 다름”은 곧 “기록 내용을 바꾸지 않음”의 증명은 아니다. 실제 `e1024a2 → 6d238db → ae82356` 차이는 모두 `A`(추가)였으므로 이번 기록에서 그러한 수정·삭제는 보이지 않는다.
- **제안:** P5를 재사용하는 향후 평가에서는 변경 종류와 실행 기록의 최초 커밋 해시를 함께 확인한다. 이번 3-5의 공개 문서에는 “경로만 다른 커밋을 허용했다”와 “실제 차이는 새 실행 파일 추가였다”를 구분해 쓰면 된다.

## 요청 항목별 대조 범위

- 저장된 `judge_report.json`의 결과표, 유형별·묶음별 표, 해석 표, 교차 확인 효과를 두 `cases.jsonl`·`summary.json`·`final.json`과 대조했다. **419/480, 476/480, 112/120, 24회 출력 한도, 9,679.8초(보고서 반올림 9,680초), 중앙값 11.9초, 최대 120.96초, 묶음 71개**는 기록과 맞았다. `71`은 원본 근거 행 개수가 아니라 회사×기준×계정 묶음 수이며, 이 중 23개는 연결+별도 나란히 묶음이다.
- `proposed_years`를 제거해 메모리에서 교차 확인 600건을 다시 채점했다. **8개 ID 모두** 보고서와 같고, 기존에는 없던 `ungrounded`가 생긴다. 이 8건은 원래도 `automatic_passed=false`인 불필요한 되묻기였다. 따라서 옛 채점기 기준으로는 “근거 없는 숫자 0” 문턱만 실패한다. 실행 기록은 고치지 않았다.
- 표본 함수에 저장된 시드 `3505`를 적용하니 교차 확인 40개·규칙만 20개의 ID가 각 `final.json.sample`과 정확히 같았다. 자동 실패 69+7건을 합쳐 109+27건이 실제 사람 검토에 있다. 비표준 행의 “자료 없음”은 값이 있는 원본을 부인하는 잘못된 **설명**이므로 `failure_kind=설명`은 기준과 맞는다. 동시에 결과 칸은 `잘못된 거절`로 우선 분류되어 “설명 실패 0”에 들어가지 않는다. 3-1 U07의 불필요한 되묻기도 `body_ok=true`, 최종 결과 실패로 처리됐으므로 3-5의 같은 처리와 일치한다.
- 통과 표본 밖 수치 답 **15건**의 질문·정답 구조·보이는 본문을 직접 읽었다: 재작성 A1-022, A1-045, A6-028, A6-038, A6-040; 부호 전환 A3-041, A3-043, A3-050, A3-054, A4-031; A6 A6-001, A6-003, A6-004, A6-005, A6-006. 재작성 7건 전체 중 나머지 A6-029는 이미 사람 검토 통과, A6-047은 모델이 불필요하게 되물은 실패였다. 직접 읽은 15건에서는 회사·기간·기준·방향 및 보고서에 없는 원인 단정의 새 오류를 찾지 못했다. 이 확인은 전체 419건의 독립적인 원본 재감사를 뜻하지 않는다.
- 제품 결함 원인은 실제 코드 경로와 맞는다. `dart_review/crosscheck.py:149-156,302-344`는 모델 회사 이름을 `resolve_company`에 넣고 두 정규 키를 비교한다. `LG Energy Solution`과 `LG ENSOL`은 현재 회사 집합에서 `LG` 그룹으로 잡혀 `('clarify_company','LG')`가 되므로, 한국어 이름과 불일치한다. `dart_review/baseline.py:198-203`은 처음 보는 `SK하이닉스`·`현대자동차`를 `unreadable`로 두고, `dart_review/crosscheck.py:342-344`는 양쪽 키가 없으면 답을 보류한다(B5 3건). B8-002는 모델이 `unsupported`를 반환하면서 회사 문자열을 비워 `model_key=None`이 되었고, `crosscheck.py:331-336`의 규칙 한쪽만 유효한 경우에 들어가 보류됐다.
- 직접 검증하지 않은 것: 3-5 전체 원본 캐시 행의 독립 재계산, 419개 출력 본문의 전수 사람 검토, 실제 모델 재현성, 향후 버전의 P5 우회 가능성 실증. 이 감사에서는 API·Ollama·평가 재실행을 하지 않았다.

**판단:** 저장된 사후 P5 판정기에 따른 `기준 충족` 수치 자체를 뒤집을 근거는 찾지 못했다. 다만 위 1~6번의 통계 정의·원인 분류·절차 표기를 바로잡은 뒤 공개하는 편이 정직하다. 이 문서는 새 공식 판정이 아니다.
