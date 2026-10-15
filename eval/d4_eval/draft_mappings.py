"""Claude's first-pass D4 mapping decisions (contract 4.2), written as data so each one can be reviewed.

    python eval/d4_eval/draft_mappings.py   # writes eval/d4_eval/gold/<doc>.mapping.json as "draft" (never overwrites)

Every decision rests on the PDF's text layer (pdfplumber lines, page and printed text quoted in the note) and on
the cached OpenDART statements (cache/d4, fnlttSinglAcntAll 2025 11011 CFS); sums and differences are in 원 and
were checked exactly. The user reads and confirms them (status "confirmed"); until then no score is official.
Documents whose items follow one pattern (쌍용씨앤이's three-column balance sheet, DSR's statements the builder did
not find) are drafted by functions below from the printed lines, with each item's own numbers in its note.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / "eval" / "d4_eval" / "gold"
BASIS = ("PDF 글자 층(pdfplumber)의 인쇄 줄과 OpenDART 캐시(cache/d4, fnlttSinglAcntAll, 2025, 11011, CFS)의 값을 항목마다 "
         "대조했다. 합·차는 원 단위 정수로 계산해 맞는 것만 적었다. 사용자 확인 전이다.")


def keep(note: str) -> dict:
    return {"decision": "keep", "note": note}


def ignore(note: str) -> dict:
    return {"decision": "ignore", "note": note}


def add(note: str, cells: list[dict] | None = None) -> dict:
    return {"decision": "add", "note": note, **({"cells": cells} if cells is not None else {})}


def cell(statement_id: str, page: int, label: str, period: int, printed: str, value: int | None) -> dict:
    return {"statement_id": statement_id, "page": page, "label": label, "period": period, "printed": printed, "value": value}


DOOSAN_IS = "연결손익계산서@12"
DECISIONS: dict[str, dict[str, dict]] = {
    "07_01258710": {  # 이노메트리
        "n1": add("8쪽 아래(위치 778) '비지배지분 - -': 바로 아래가 쪽 바닥글(814)이고 자본총계는 9쪽 첫 줄이다. 바닥글이 아니라 "
                  "재무상태표의 행이므로 '-' 칸 둘(당기·전기)을 정답에 넣는다(값 없음 칸)."),
    },
    "15_00479705": {  # 케스피온
        "n1": add("10쪽 아래(위치 783) '계속영업희석주당손익 (135) (78)': 주당손익 단락(711~783)의 행이고 다음 쪽에 "
                  "'중단영업희석주당손익'이 이어진다. 바닥글이 아니므로 제안된 칸 둘(-135, -78, 주당 행이라 원 단위)을 넣는다."),
        "n2": ignore("OpenDART '계속영업희석주당이익(손실)' 당기 -135는 10쪽 '계속영업희석주당손익 (135)'의 당기 칸으로, n1의 결정으로 "
                     "이미 정답에 들어간다. 따로 더하지 않는다."),
        "n3": ignore("OpenDART '계속영업희석주당이익(손실)' 전기 -78은 10쪽 '계속영업희석주당손익 ... (78)'의 전기 칸으로, n1의 결정으로 "
                     "이미 정답에 들어간다. 따로 더하지 않는다."),
    },
    "19_00164788": {  # 현대모비스
        "n1": add("11쪽 '기본주당이익(주35) 40,861원 44,939원': 금액 뒤에 '원'이 붙어 인쇄돼 정답 생성기가 칸을 만들지 못했다. "
                  "OpenDART '기본주당이익(손실)' 당기 40,861과 같다. 주당 행이라 원 단위로 당기 칸을 더한다.",
                  [cell("연결손익계산서@11", 11, "기본주당이익", 0, "40,861", 40861)]),
        "n2": add("11쪽 같은 줄의 전기 '44,939원'은 OpenDART '기본주당이익(손실)' 전기 44,939와 같다. 주당 행이라 원 단위로 "
                  "전기 칸을 더한다.", [cell("연결손익계산서@11", 11, "기본주당이익", 1, "44,939", 44939)]),
    },
    "16_00137915": {  # 엠엑스로보틱스
        "n1": ignore("11쪽 '해외사업환산손익 25 (262,505,175) 108,078,127' 한 줄만 금액이 있다(위의 '재분류될 수 있는 항목'은 금액 "
                     "없는 제목 줄). 인쇄 당기 칸은 OpenDART 소계 '당기손익으로 재분류될 수 있는 항목' -262,505,175와 짝지어졌고, "
                     "이 항목(해외사업장환산외환차이 당기 -262,505,175)은 같은 인쇄 칸의 두 번째 저장이다."),
        "n2": ignore("같은 11쪽 줄의 전기 108,078,127: OpenDART 소계(재분류될 수 있는 항목) 전기 108,078,127과 이미 짝지어졌고, "
                     "해외사업장환산외환차이 전기 108,078,127은 같은 인쇄 칸의 두 번째 저장이다."),
        "n3": ignore("11쪽 '순확정급여의 재측정요소 20 1,531,332,970 (953,450,433)' 한 줄만 금액이 있다. 인쇄 당기 칸은 OpenDART 소계 "
                     "'당기손익으로 재분류되지 않는항목' 1,531,332,970과 짝지어졌고, 이 항목(순확정급여부채 재측정 요소 당기)은 두 번째 저장이다."),
        "n4": ignore("같은 11쪽 줄의 전기 (953,450,433): OpenDART 소계(재분류되지 않는항목) 전기 -953,450,433과 이미 짝지어졌고, "
                     "순확정급여부채 재측정 요소 전기 -953,450,433은 두 번째 저장이다."),
        "n5": ignore("OpenDART '현금및현금성자산의순증가(감소)' 당기 4,429,597,407은 14쪽에 인쇄되지 않았다. 인쇄된 'IV. 현금및현금성자산의 "
                     "증감 4,529,550,779'와 'V. 현금및현금성자산의 환율변동효과 (99,953,372)'의 합이다(4,529,550,779 - 99,953,372 = "
                     "4,429,597,407)."),
        "n6": ignore("OpenDART '현금및현금성자산의순증가(감소)' 전기 -8,610,292,059: 14쪽 전기 '(8,640,932,067)'와 환율변동효과 전기 "
                     "'30,640,008'의 합이다(-8,640,932,067 + 30,640,008 = -8,610,292,059). 이 합은 인쇄되지 않았다."),
    },
    "06_00148920": {  # 조광페인트
        "n1": keep("13쪽 '1. 투자활동으로 인한 현금유입액 7,348,111,554 478,845,949'의 당기 칸: 금액이 인쇄된 소계 행이다. OpenDART는 이 "
                   "중간 소계를 저장하지 않는다. 인쇄 그대로 정답에 둔다."),
        "n2": keep("13쪽 같은 줄 '투자활동으로 인한 현금유입액'의 전기 478,845,949: 인쇄된 소계 칸, OpenDART에 없는 중간 소계."),
        "n3": keep("13쪽 '2. 투자활동으로 인한 현금유출액 (17,107,009,148) (15,915,694,315)'의 당기 칸: 금액이 인쇄된 소계 행이고 "
                   "OpenDART에 이 소계가 없다."),
        "n4": keep("13쪽 같은 줄 '투자활동으로 인한 현금유출액'의 전기 (15,915,694,315): 인쇄된 소계 칸, OpenDART에 없다."),
        "n5": keep("13쪽 '1. 재무활동으로 인한 현금유입액 134,667,506,995 203,916,470,348'의 당기 칸: 금액이 인쇄된 소계 행이고 "
                   "OpenDART에 이 소계가 없다."),
        "n6": keep("13쪽 같은 줄 '재무활동으로 인한 현금유입액'의 전기 203,916,470,348: 인쇄된 소계 칸, OpenDART에 없다."),
        "n7": keep("13쪽 '2. 재무활동으로 인한 현금유출액 (127,340,856,758) (214,601,031,196)'의 당기 칸: 금액이 인쇄된 소계 행이고 "
                   "OpenDART에 이 소계가 없다."),
        "n8": keep("13쪽 같은 줄 '재무활동으로 인한 현금유출액'의 전기 (214,601,031,196): 인쇄된 소계 칸, OpenDART에 없다."),
    },
    "13_00184667": {  # 유진기업
        "n1": keep("10쪽 '당기순이익의 귀속:' 아래 '합계 (24,486,386,033) (100,746,405,683)'의 당기 칸: 인쇄된 합계 행이다. OpenDART "
                   "'당기순이익' -24,486,386,033은 위쪽의 인쇄 행 '당기순손익 (24,486,386,033)'(위치 374)과 이미 짝지어져 이 행의 짝이 없다. 인쇄 그대로 둔다."),
        "n2": keep("10쪽 같은 '합계'(당기순이익의 귀속) 줄의 전기 (100,746,405,683): 인쇄된 합계 칸. OpenDART 당기순이익 전기 -100,746,405,683은 위쪽 "
                   "'당기순손익' 행(위치 374)과 이미 짝지어졌다."),
        "n3": keep("10쪽 '총포괄이익의 귀속:' 아래 '합계 (16,620,948,746) (107,899,564,013)'의 당기 칸: 인쇄된 합계 행이다. OpenDART "
                   "'총포괄손익 합계' -16,620,948,746은 위쪽 인쇄 행 '총포괄손익'(위치 550)과 이미 짝지어졌다."),
        "n4": keep("10쪽 같은 '합계'(총포괄이익의 귀속) 줄의 전기 (107,899,564,013): 인쇄된 합계 칸. OpenDART '총포괄손익 합계' 전기는 위쪽 "
                   "'총포괄손익' 행(위치 550)과 이미 짝지어졌다."),
        "n5": ignore("OpenDART '후속적으로 당기손익으로 재분류되는 포괄손익' 당기 -116,085,838: 10쪽의 이 제목 줄은 금액 없이 인쇄됐다. "
                     "아래 두 행의 합이다('해외사업환산손익 (110,328,370)' + '지분법자본변동 (5,757,468)' = -116,085,838)."),
        "n6": ignore("같은 소계의 전기 1,200,298,992: 10쪽 전기 '565,718,837' + '634,580,155' = 1,200,298,992. 금액 없는 제목 줄의 값이다."),
        "n7": ignore("OpenDART '후속적으로 당기손익으로 재분류되지 않는 포괄손익' 당기 7,981,523,125: 10쪽 제목 줄에는 금액이 없다. "
                     "아래 네 행의 합이다(-516,701,240 - 597,827,518 + 1,244,744,543 + 7,851,307,340 = 7,981,523,125)."),
        "n8": ignore("같은 소계(재분류되지 않는)의 전기 -8,353,457,322: 10쪽 전기 -4,576,482,260 - 903,694,109 - 1,451,987,711 - "
                     "1,421,293,242 = -8,353,457,322. 금액 없는 제목 줄의 값이다."),
    },
    "05_00117212": {  # 두산
        "n1": add("12쪽 '구형우선주 기본주당손익 4,280원 (12,665)원': 금액마다 '원'이 붙어 칸이 만들어지지 않았다. OpenDART "
                  "'구형우선주 기본주당이익(손실)' 당기 4,280과 같다. 주당 행(원 단위) 당기 칸을 더한다.",
                  [cell(DOOSAN_IS, 12, "구형우선주 기본주당손익", 0, "4,280", 4280)]),
        "n2": add("12쪽 '구형우선주 기본주당손익'의 전기 '(12,665)원' = OpenDART 구형우선주 기본주당이익(손실) 전기 -12,665. "
                  "주당 행 전기 칸을 더한다.", [cell(DOOSAN_IS, 12, "구형우선주 기본주당손익", 1, "(12,665)", -12665)]),
        "n3": add("12쪽 '구형우선주 희석주당손익 4,280원 (12,665)원'(기본과 별도의 줄, 위치 434)의 당기 4,280 = OpenDART 구형우선주 "
                  "희석주당이익(손실) 당기 4,280. 당기 칸을 더한다.", [cell(DOOSAN_IS, 12, "구형우선주 희석주당손익", 0, "4,280", 4280)]),
        "n4": add("12쪽 '구형우선주 희석주당손익'(위치 434)의 전기 '(12,665)원' = OpenDART 구형우선주 희석주당이익(손실) 전기 -12,665. "
                  "전기 칸을 더한다.", [cell(DOOSAN_IS, 12, "구형우선주 희석주당손익", 1, "(12,665)", -12665)]),
        "n5": add("12쪽 '보통주 기본주당손익 4,230원 (12,715)원'(위치 389)의 당기 4,230 = OpenDART 보통주 기본주당이익(손실) 당기 "
                  "4,230. 당기 칸을 더한다.", [cell(DOOSAN_IS, 12, "보통주 기본주당손익", 0, "4,230", 4230)]),
        "n6": add("12쪽 '보통주 기본주당손익'의 전기 '(12,715)원' = OpenDART 보통주 기본주당이익(손실) 전기 -12,715. 전기 칸을 더한다.",
                  [cell(DOOSAN_IS, 12, "보통주 기본주당손익", 1, "(12,715)", -12715)]),
        "n7": add("12쪽 '보통주 희석주당손익 4,194원 (12,480)원'(위치 404)의 당기 4,194 = OpenDART 보통주 희석주당이익(손실) 당기 "
                  "4,194. 당기 칸을 더한다.", [cell(DOOSAN_IS, 12, "보통주 희석주당손익", 0, "4,194", 4194)]),
        "n8": add("12쪽 '보통주 희석주당손익'의 전기 '(12,480)원' = OpenDART 보통주 희석주당이익(손실) 전기 -12,480. 전기 칸을 더한다.",
                  [cell(DOOSAN_IS, 12, "보통주 희석주당손익", 1, "(12,480)", -12480)]),
        "n9": ignore("OpenDART '후속적으로 당기손익으로 재분류되는 항목' 당기 343,478백만원: 13쪽 이 제목 줄('후속적으로 당기손익으로 "
                     "재분류되는 항목:')은 금액 없이 인쇄됐다. 아래 세 행의 합이다(8,804 + 334,062 + 612 = 343,478)."),
        "n10": ignore("같은 소계(재분류되는 항목)의 전기 629,646백만원: 13쪽 전기 20,148 + 604,552 + 4,946 = 629,646. 금액 없는 제목 줄."),
        "n11": ignore("OpenDART '후속적으로 당기손익으로 재분류되지 않는 항목' 당기 -15,489백만원: 13쪽 제목 줄은 금액 없이 인쇄됐다. "
                      "아래 네 행의 합이다(-12,750 + 6,419 - 4,280 - 4,878 = -15,489)."),
        "n12": ignore("같은 소계(재분류되지 않는 항목)의 전기 -69,007백만원: 13쪽 전기 -55,182 + 9 - 4,234 - 9,600 = -69,007."),
        "n13": keep("16쪽 '1. 영업활동에서 창출된 현금 35 1,650,429 1,053,909'의 당기 칸: 금액이 인쇄된 소계 행이고 OpenDART에 이 "
                    "소계가 없다. 인쇄 그대로 둔다."),
        "n14": keep("16쪽 같은 줄 '영업활동에서 창출된 현금'의 전기 1,053,909(백만원): 인쇄된 소계 칸, OpenDART에 없다."),
        "n15": keep("16쪽 '1. 투자활동으로 인한 현금유입액 929,080 655,310'의 당기 칸: 금액이 인쇄된 소계 행, OpenDART에 없다."),
        "n16": keep("16쪽 같은 줄 '투자활동으로 인한 현금유입액'의 전기 655,310(백만원): 인쇄된 소계 칸, OpenDART에 없다."),
        "n17": keep("16쪽 '2. 투자활동으로 인한 현금유출액 (1,359,522) (1,650,070)'의 당기 칸: 금액이 인쇄된 소계 행, OpenDART에 없다."),
        "n18": keep("16쪽 같은 줄 '투자활동으로 인한 현금유출액'의 전기 (1,650,070)(백만원): 인쇄된 소계 칸, OpenDART에 없다."),
        "n19": keep("16쪽 '1. 재무활동으로 인한 현금유입액 2,354,578 3,987,067'의 당기 칸: 금액이 인쇄된 소계 행, OpenDART에 없다."),
        "n20": keep("16쪽 같은 줄 '재무활동으로 인한 현금유입액'의 전기 3,987,067(백만원): 인쇄된 소계 칸, OpenDART에 없다."),
        "n21": keep("17쪽 '2. 재무활동으로 인한 현금유출액 (1,654,548) (3,413,208)'의 당기 칸: 금액이 인쇄된 소계 행, OpenDART에 없다."),
        "n22": keep("17쪽 같은 줄 '재무활동으로 인한 현금유출액'의 전기 (3,413,208)(백만원): 인쇄된 소계 칸, OpenDART에 없다."),
    },
    "17_00759294": {  # 와이솔
        "n1": keep("11쪽 'X. 당기순이익(손실)의 귀속 (42,131,712,633) 10,998,930,304'의 당기 칸: 제목 줄에 합계 금액이 인쇄됐다. "
                   "OpenDART 당기순이익(손실)은 위쪽 인쇄 행 '당기순이익(손실)'과 이미 짝지어졌다. 인쇄 그대로 둔다."),
        "n2": keep("11쪽 같은 '당기순이익(손실)의 귀속' 줄의 전기 10,998,930,304: 인쇄된 칸, OpenDART 값은 위쪽 당기순이익 행과 짝지어졌다."),
        "n3": keep("11쪽 'XI. 총포괄손익의 귀속 (46,804,349,639) 20,426,613,649'의 당기 칸: 제목 줄에 합계 금액이 인쇄됐다. OpenDART "
                   "총포괄손익은 위쪽 인쇄 행과 이미 짝지어졌다."),
        "n4": keep("11쪽 같은 '총포괄손익의 귀속' 줄의 전기 20,426,613,649: 인쇄된 칸, OpenDART 값은 위쪽 총포괄손익 행과 짝지어졌다."),
        "n5": ignore("11쪽 '기본 및 희석주당손익 30 (1,522) 399'는 한 줄이다. 당기 (1,522)는 OpenDART '계속영업기본주당이익(손실)'과 "
                     "짝지어졌고, 이 항목(계속영업희석주당이익(손실) 당기 -1,522)은 같은 인쇄 칸의 두 번째 저장이다."),
        "n6": ignore("11쪽 같은 '기본 및 희석주당손익' 줄의 전기 399: OpenDART 계속영업기본주당이익(손실) 전기 399와 짝지어졌고, "
                     "계속영업희석주당이익(손실) 전기 399는 두 번째 저장이다."),
        "n7": keep("13쪽 '1. 영업에서 창출된 현금흐름 6,462,747,308 42,099,938,396'의 당기 칸: 금액이 인쇄된 소계 행, OpenDART에 없다."),
        "n8": keep("13쪽 같은 줄 '영업에서 창출된 현금흐름'의 전기 42,099,938,396: 인쇄된 소계 칸, OpenDART에 없다."),
        "n9": keep("13쪽 '1. 투자활동으로 인한 현금유입액 95,845,790,021 12,664,480,631'의 당기 칸: 인쇄된 소계 행, OpenDART에 없다."),
        "n10": keep("13쪽 같은 줄 '투자활동으로 인한 현금유입액'의 전기 12,664,480,631: 인쇄된 소계 칸, OpenDART에 없다."),
        "n11": keep("13쪽 '당기손익-공정가치측정금융자산의 처분 18,611,806,140 165,000'의 당기 칸: 인쇄값은 18,611,806,140이고 OpenDART "
                    "같은 이름 당기는 25,111,806,140이다(차이 6,500,000,000). 정답은 인쇄된 값이다."),
        "n12": keep("13쪽 '기타금융자산의 감소 60,402,421,487 12,516,398,845'의 당기 칸: OpenDART '기타금융자산의 처분' 당기는 "
                    "53,902,421,487(차이 6,500,000,000, n11과 반대 방향). 정답은 인쇄된 값이다."),
        "n13": keep("13쪽 '2. 투자활동으로 인한 현금유출액 (82,807,276,287) (84,852,863,063)'의 당기 칸: 인쇄된 소계 행, OpenDART에 없다."),
        "n14": keep("13쪽 같은 줄 '투자활동으로 인한 현금유출액'의 전기 (84,852,863,063): 인쇄된 소계 칸, OpenDART에 없다."),
        "n15": keep("13쪽 '당기손익-공정가치측정금융자산의 취득 (16,760,379,130) (1,405,507,415)'의 당기 칸: OpenDART 같은 이름 당기는 "
                    "23,260,379,130이다(차이 6,500,000,000). 정답은 인쇄된 값이다."),
        "n16": keep("13쪽 '기타금융자산의 증가 (44,091,208,281) (50,434,474,620)'의 당기 칸: OpenDART '기타금융자산의 취득' 당기는 "
                    "37,591,208,281(차이 6,500,000,000, n15와 반대 방향). 정답은 인쇄된 값이다."),
        "n17": keep("13쪽 '단기차입금의 차입 8,586,040,200 10,916,448,000'의 당기 칸: 바로 위 소계 '1. 재무활동으로 인한 현금유입액'이 "
                    "같은 값이라 OpenDART '단기차입금의 증가' 당기 8,586,040,200이 그 소계 행과 먼저 짝지어졌다. 두 행 모두 인쇄됐으므로 둔다."),
        "n18": keep("13쪽 같은 '단기차입금의 차입' 줄의 전기 10,916,448,000: 위 소계(재무활동 현금유입액 전기 10,916,448,000)가 OpenDART "
                    "'단기차입금의 증가' 전기와 먼저 짝지어졌다. 인쇄된 칸이므로 둔다."),
        "n19": keep("13쪽 '2. 재무활동으로 인한 현금유출액 (30,036,188,338) (18,886,057,150)'의 당기 칸: 인쇄된 소계 행, OpenDART에 없다."),
        "n20": keep("13쪽 같은 줄 '재무활동으로 인한 현금유출액'의 전기 (18,886,057,150): 인쇄된 소계 칸, OpenDART에 없다."),
        "n21": ignore("OpenDART '당기손익-공정가치측정금융자산의 처분' 당기 25,111,806,140은 13쪽에 인쇄되지 않았다. 인쇄는 18,611,806,140"
                      "(n11)이고, 차이 6,500,000,000은 '기타금융자산의 감소'(인쇄 60,402,421,487, OpenDART 53,902,421,487)로 옮겨져 "
                      "두 항목의 합(79,014,227,627)은 같다."),
        "n22": ignore("OpenDART '기타금융자산의 처분' 당기 53,902,421,487은 인쇄되지 않았다. 인쇄 '기타금융자산의 감소' 60,402,421,487(n12)과 "
                      "6,500,000,000 다르고, n21의 차이와 상쇄된다."),
        "n23": ignore("OpenDART '당기손익-공정가치측정금융자산의 취득' 당기 23,260,379,130은 인쇄되지 않았다. 인쇄는 (16,760,379,130)(n15)이고 "
                      "차이 6,500,000,000은 '기타금융자산의 증가'로 옮겨져 두 항목 합(60,851,587,411)은 같다."),
        "n24": ignore("OpenDART '기타금융자산의 취득' 당기 37,591,208,281은 인쇄되지 않았다. 인쇄 '기타금융자산의 증가' (44,091,208,281)(n16)과 "
                      "6,500,000,000 다르고, n23의 차이와 상쇄된다."),
    },
}


PDF_DIR = Path.home() / "Desktop" / "D4"  # the evaluation PDFs (not committed, contract 8)
AMOUNT = re.compile(r"^\(?[-−△]?\d{1,3}(,\d{3})+\)?$|^-$")
PERIOD_NAMES = ("당기", "전기")


def three_column_balance_sheet(name: str, pdf: Path) -> dict[str, dict]:
    """쌍용씨앤이: the balance sheet prints 당기, 전기 (restated), and 전기초 (unaudited) on every amount line, so the
    builder leaves each line as a "slots" item and each OpenDART value as "dart_only". Each line gets its 당기 and 전기
    cells (the gold has two periods; 전기초 is not one); each OpenDART value is the cell a slots item adds."""
    sys.path.insert(0, str(ROOT / "eval"))
    import d4_gold
    gold = json.loads((GOLD / f"{name}.gold.json").read_text(encoding="utf-8"))
    statement = next(s for s in gold["statements"] if s["kind"] == "BS")
    lines = {(l["page"], " ".join(w["text"] for w in l["words"])): l for l in d4_gold.lines_of(pdf)}
    pool = [n for n in gold["needs_mapping"] if n["why"] == "dart_only"]
    decisions, used = {}, {}
    for need in (n for n in gold["needs_mapping"] if n["why"] == "slots"):
        line = lines[(need["page"], need["line"])]
        words = line["words"]
        amounts = [w for w in words if AMOUNT.match(w["text"]) and w["x0"] > 280]
        columns = ["당기" if w["x1"] < 375 else "전기" if w["x1"] < 465 else "전기초" for w in amounts]
        if columns != ["당기", "전기", "전기초"]:
            raise ValueError(f"{need['id']}: columns {columns}")
        label = d4_gold.clean(" ".join(w["text"] for w in words if w["x0"] < 200))
        cells, parts = [], []
        for period, word in enumerate(amounts[:2]):
            printed = word["text"]
            value = None if printed == "-" else d4_gold.value_of(printed, 1)
            cells.append(cell(statement["id"], need["page"], label, period, printed, value))
            match = next((d for d in pool if d["id"] not in used and d["period"] == period and value is not None
                          and abs(d["value"]) == abs(value)), None)
            if match:
                used[match["id"]] = (need["id"], label, period, printed)
                parts.append(f"{PERIOD_NAMES[period]} {printed} = OpenDART '{match['name']}' {PERIOD_NAMES[period]} {match['value']:,}({match['id']})")
            else:
                parts.append(f"{PERIOD_NAMES[period]} {printed}" + (" ('-' 칸)" if value is None else " (OpenDART에 같은 값 없음)"))
        decisions[need["id"]] = add(
            f"{need['page']}쪽 '{need['line']}': 이 재무상태표는 당기·전기(재작성)·전기초(감사받지 아니한 재무제표) 세 열이다"
            f"(금액 오른쪽 끝 366·455·543). 정답 기간인 당기·전기 두 칸을 더한다: " + "; ".join(parts)
            + f". 전기초 {amounts[2]['text']}는 정답 기간이 아니라 넣지 않는다.", cells)
    for need in pool:
        if need["id"] not in used:
            raise ValueError(f"{need['id']}: OpenDART {need['name']} {need['period']} {need['value']} matches no slots cell")
        slot, label, period, printed = used[need["id"]]
        decisions[need["id"]] = ignore(
            f"OpenDART '{need['name']}' {PERIOD_NAMES[need['period']]} {need['value']:,}({need['id']}): 인쇄된 칸이다. "
            f"{slot}의 결정으로 '{label}' 줄의 {PERIOD_NAMES[period]} 칸({printed})을 이미 더하므로 따로 더하지 않는다.")
    return dict(sorted(decisions.items(), key=lambda item: int(item[0][1:])))


# DSR: titles printed with a space ("연결 재무상태표") and period lines as "2025.12.31 현재", so the builder found no
# statement. Each statement is transcribed from the text layer: amounts right of the note column, the period by the
# amount's right edge (당기 detail/subtotal end at x 336-341 / 403-409, 전기 at 473-476 / 543), the label from the
# words that are not numbers. Three labels printed on two lines around their amount line, and one amount the text
# layer split over two lines, are given explicitly (MERGED, SPLIT_AMOUNT).
DSR_STATEMENTS = (  # (need id, kind, title, first page, last page)
    ("n1", "BS", "연결재무상태표", 7, 8), ("n4", "IS", "연결손익계산서", 9, 9), ("n3", "CIS", "연결포괄손익계산서", 10, 10),
    ("n2", "CF", "연결현금흐름표", 12, 12),
)
PERIOD_EDGE = 420  # right edge of an amount: at most this is 당기, beyond it 전기
SKIP = re.compile(r"^(연결 ?(재무상태표|손익계산서|포괄손익계산서|현금흐름표)|제 ?6[12] ?기|DSR주식회사와|\(단위|과 목|주 석|별첨 주석|전자공시시스템)")
MERGED = {  # (page, top of the amount line): the label printed above and below it
    (7, 221): "최초인식시점 또는 그 이후에 지정된 유동 당기손익인식금융자산",
    (7, 312): "최초인식시점 또는 그 이후에 지정된 비유동 당기손익인식금융자산",
    (10, 236): "지분법 적용대상 관계기업과 공동기업의 기타포괄손익에 대한 지분(세후기타포괄손익)",
}
MERGED_PARTS = {(7, 213), (7, 229), (7, 304), (7, 320), (10, 228), (10, 244)}  # their label-only lines
SPLIT_AMOUNT = {(8, 62): ("이익잉여금", "219,722,694,808", {(8, 54), (8, 70)})}  # 당기 printed "219,722,694,80" / "8"
NOTE_REF = re.compile(r"^\d{1,2}(,\d{1,2})*,?$")


def _dsr_rows(pdf: Path, first: int, last: int) -> list[tuple[int, int, str, list[tuple[int, str]]]]:
    """(page, top, label, [(period, printed)]) of each amount line of a DSR statement."""
    sys.path.insert(0, str(ROOT / "eval"))
    import d4_gold
    rows = []
    split_parts = {part for _, _, parts in SPLIT_AMOUNT.values() for part in parts}
    for line in d4_gold.lines_of(pdf):
        page, words = line["page"], line["words"]
        top = round(words[0]["top"])
        text = " ".join(w["text"] for w in words)
        if not first <= page <= last or top > 790 or SKIP.match(text) or (page, top) in MERGED_PARTS | split_parts:
            continue
        amounts = [w for w in words if AMOUNT.match(w["text"]) or (re.fullmatch(r"\(?\d{1,3}\)?", w["text"]) and w["x0"] > 330)]
        amounts = [w for w in amounts if w["x0"] > 270]
        label_words = [w for w in words if w not in amounts and not (NOTE_REF.match(w["text"]) and w["x1"] < 280)]
        label = MERGED.get((page, top)) or d4_gold.clean(" ".join(w["text"] for w in label_words))
        cells = [(0 if w["x1"] <= PERIOD_EDGE else 1, w["text"]) for w in amounts]
        if (page, top) in SPLIT_AMOUNT:
            name, printed, _ = SPLIT_AMOUNT[(page, top)]
            assert label == name, (label, name)
            cells = [(0, printed)] + cells
        if not cells:
            continue  # a heading without amounts
        if sorted(period for period, _ in cells) != [0, 1]:
            raise ValueError(f"DSR {page}/{top} '{text}': periods {cells}")
        rows.append((page, top, label, cells))
    return rows


def dsr(name: str, pdf: Path) -> dict[str, dict]:
    sys.path.insert(0, str(ROOT / "eval"))
    import d4_gold
    from dart_review.cache import ResponseCache
    from dart_review.client import DartClient
    corp = json.loads((GOLD / f"{name}.gold.json").read_text(encoding="utf-8"))
    items = DartClient(ResponseCache(ROOT / "cache" / "d4"), offline=True).financial_statements(
        name.split("_")[1], 2025, "11011", "CFS").json()["list"]
    assert corp["source"]["file"] == pdf.name
    decisions = {}
    for need_id, kind, title, first, last in DSR_STATEMENTS:
        statement = {"id": f"{title}@{first}", "kind": kind, "title": title, "consolidated": True, "page": first,
                     "end_page": last, "unit_text": "원"}
        rows = _dsr_rows(pdf, first, last)
        cells = [cell(statement["id"], page, label, period, printed, None if printed == "-" else d4_gold.value_of(printed, 1))
                 for page, _, label, row in rows for period, printed in row]
        pool = [{"name": i["account_nm"], "period": period, "value": int(t.replace(",", "")), "used": False}
                for i in items if i["sj_div"] == kind for period, field in ((0, "thstrm_amount"), (1, "frmtrm_amount"))
                if re.fullmatch(r"-?[\d,]+", (t := (i.get(field) or "").strip())) and int(t.replace(",", ""))]
        unmatched = []
        for c in cells:
            if c["value"] is None:
                continue
            match = next((e for e in pool if not e["used"] and e["period"] == c["period"] and abs(e["value"]) == abs(c["value"])), None)
            if match:
                match["used"] = True
            else:
                unmatched.append(f"{c['page']}쪽 '{c['label']}' {PERIOD_NAMES[c['period']]} {c['printed']}")
        left = [f"{e['name']} {PERIOD_NAMES[e['period']]} {e['value']:,}" for e in pool if not e["used"]]
        printed = [c for c in cells if c["value"] is not None]
        DSR_REPORT[need_id] = {"statement": statement["id"], "cells": len(cells), "printed": len(printed),
                               "unmatched_print": unmatched, "unmatched_dart": left}
        decisions[need_id] = {
            "decision": "add_statement", "statement": statement, "cells": cells,
            "note": (f"DSR {first}~{last}쪽 '{title[:2]} {title[2:]}'(제목을 띄어 쓰고 기간 줄이 '2025.12.31 현재' 형식이라 정답 생성기가 "
                     f"찾지 못했다). 인쇄된 금액 줄 {len(rows)}개를 옮겨 적었다(금액 오른쪽 끝 x≤{PERIOD_EDGE} 당기, 그 밖 전기). "
                     f"칸 {len(cells)}개 중 인쇄 금액 {len(printed)}개, OpenDART {kind}와 일대일로 같은 값 {len(printed) - len(unmatched)}개"
                     + (f"; 짝 없는 인쇄 칸: {'; '.join(unmatched)}" if unmatched else "")
                     + (f"; 인쇄되지 않은 OpenDART 값: {'; '.join(left)}" if left else "") + ". " + DSR_NOTES[need_id]),
        }
    return decisions


DSR_REPORT: dict[str, dict] = {}
DSR_NOTES = {  # the sum checks of each transcription (원), both periods
    "n1": ("검산(당기·전기 모두 맞음): 유동자산 = 그 아래 6행의 합, 비유동자산 = 10행의 합, 자산총계 = 유동+비유동, 유동부채 = 8행, "
           "비유동부채 = 5행, 부채총계 = 유동+비유동, 지배기업 소유주 자본 = 자본금+자본잉여금+이익잉여금+기타자본구성요소, "
           "자본총계 = 지배+비지배, 자본과부채총계 = 부채총계+자본총계. 8쪽 이익잉여금 당기는 글자 층에서 '219,722,694,80'(위치 54)과 "
           "'8'(위치 70)로 끊겨 있으나 지배기업 소유주 자본 244,540,902,906 = 8,000,000,000 + 13,724,276,892 + 219,722,694,808 + "
           "3,093,931,206으로 219,722,694,808이다. 계정명이 금액 줄 위아래로 나뉜 두 행('최초인식시점 또는 그 이후에 지정된 / 유동(비유동) "
           "당기손익인식금융자산')은 두 줄을 이어 적었다. '-' 칸 5개(유동성장기부채 당기 등)는 값 없음 칸이다."),
    "n4": ("검산(당기·전기): 매출총이익 = 매출액-매출원가, 영업이익 = 매출총이익-판매비와관리비, 법인세비용차감전순이익 = 영업이익+기타수익"
           "-기타비용+금융수익-금융비용+지분법이익, 당기순이익 = 차감전순이익-법인세비용 = 지배기업소유주+비지배지분. '보통주 기본주당순이익 "
           "32 935 907'은 주당 행(원)이다."),
    "n3": ("검산(당기·전기): 기타포괄손익 = 그 아래 금액 4행의 합, 총포괄이익 = 당기순이익+기타포괄손익 = 지배+비지배 귀속. 인쇄되지 않은 "
           "OpenDART 값 중 '해외사업장환산외환차이' 두 값은 인쇄 행과 같은 값의 소계('당기손익으로 재분류될 수 있는 항목')가 먼저 짝지어진 "
           "두 번째 저장이고, '재분류되지 않는항목' 당기 593,420,357 = 625,913,410-8,797,369-23,695,684, 전기 -852,998,678 = -517,242,208"
           "-312,013,589-23,742,881은 금액 없이 인쇄된 제목 줄 '1. 당기손익으로 재분류되지 않는항목'의 합이다. 금액 줄 위아래로 나뉜 계정명 "
           "'지분법 적용대상 ... 기타포괄손익에 / 대한 지분(세후기타포괄손익)'은 이어 적었다."),
    "n2": ("검산(당기·전기): 영업활동현금흐름 = 그 아래 7행의 합, 투자활동현금흐름 = 16행, 재무활동현금흐름 = 9행, 현금및현금성자산의"
           "순증가(감소) = 영업+투자+재무+환율변동효과, 기말 = 기초+순증가. 기말현금 15,703,659,486(전기 6,983,812,113)은 재무상태표 "
           "현금및현금성자산과 같다. '-' 칸 6개(단기금융상품의 처분 당기 등)는 값 없음 칸이다."),
}


def write(name: str, decisions: dict[str, dict]) -> Path:
    path = GOLD / f"{name}.mapping.json"
    if path.exists():
        raise SystemExit(f"{path.name} exists; drafts are never overwritten (edit it and record the change)")
    mapping = {"status": "draft", "drafted_by": "Claude 1차", "confirmed_by": None, "confirmed_at": None, "basis": BASIS,
               "decisions": decisions}
    path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def main() -> int:
    sys.path.insert(0, str(ROOT / "eval"))
    import d4_gold
    drafted = dict(DECISIONS)
    drafted["11_00138224"] = three_column_balance_sheet("11_00138224", PDF_DIR / "11_쌍용씨앤이.pdf")
    drafted["18_00110608"] = dsr("18_00110608", PDF_DIR / "18_DSR.pdf")
    for need_id, report in DSR_REPORT.items():
        print("DSR", need_id, json.dumps(report, ensure_ascii=False))
    for name, decisions in drafted.items():
        gold = json.loads((GOLD / f"{name}.gold.json").read_text(encoding="utf-8"))
        # the decisions must pass the same checks the scorer applies, before they are written
        applied = d4_gold.apply_mapping(gold, {"status": "draft", "decisions": decisions})
        print(name, "ok:", len(applied["cells"]), "cells,", "unscorable:", applied["unscorable"] or "none")
        if not (GOLD / f"{name}.mapping.json").exists():
            write(name, decisions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
