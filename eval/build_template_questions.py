"""Generate the 3-5 template questions (docs/EVAL_CONTRACT_3-5.ko.md section 4).

1. Every combination of company x basis x account x period for each family
   is listed (``grid``), within the cached periods (section 4.4).
2. The gold rules of eval/build_template_gold.py fill in each combination's
   expectation from the raw cache; a combination they cannot name one cell
   for is excluded, with its reason, before any sampling (section 4.1 step 2).
3. A fixed seed draws each family's count, spread evenly over the companies.
4. A template and the variants (alias, relative year, account synonym,
   explicit basis) are drawn with the same seed and written out.

Nothing here reads a product answer. The same code and seed always give the
same files.

    python eval/build_template_questions.py          # write questions.json and excluded.json
    python eval/build_template_questions.py --check  # fail if either committed file is stale
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "eval")]

from build_gold import GoldError, no_key  # noqa: E402
from build_template_gold import CACHE, FOLDER, QUESTIONS, Excluded, expectation, tags  # noqa: E402
from dart_review.accounts import ACCOUNTS  # noqa: E402
from dart_review.cache import ResponseCache  # noqa: E402
from dart_review.client import DartClient  # noqa: E402
from dart_review.companies import SEALED_EVAL_COMPANIES, using_company_set  # noqa: E402

EXCLUDED = FOLDER / "excluded.json"
SEED = 20261009  # contract section 4.1
REFERENCE_DATE = "2026-10-08"  # contract section 2
VERSION = "3-5 v1"
REVIEW_POLICY = {"seed": 3505, "sample": {"crosscheck": 40, "baseline": 20}}  # contract section 8

# contract section 4.2: family -> (count, label)
FAMILIES = {
    "A1": (60, "연간 값 조회"), "A2": (60, "분기 값 조회"), "A3": (60, "연간 전년 비교"), "A4": (60, "분기 3개월 전년 비교"),
    "A5": (60, "누적 전년 비교"), "A6": (80, "재무상태표 분기말 전년 비교"), "A7": (40, "재무상태표 연말 전년 비교"),
    "A8": (60, "연결·별도 나란히"),
    "B1": (25, "4분기 3개월"), "B2": (20, "현금흐름 분기 3개월"), "B3": (15, "2014년"), "B4": (15, "범위 밖 계정"),
    "B5": (15, "범위 밖 회사"), "B6": (10, "계정 모호"), "B7": (10, "그룹명"), "B8": (10, "복합 질문"),
}
IS_ACCOUNTS = ("revenue", "operating_income", "net_income")
CF_ACCOUNT = "operating_cash_flow"
BS_ACCOUNTS = ("total_assets", "total_liabilities")
COMPANIES = dict(sorted(SEALED_EVAL_COMPANIES.items(), key=lambda item: item[1]))  # corp code -> name, by name
# the 3-1 alias table (contract 3-1 section 4.4), by company
ALIASES = {"00266961": ("네이버",), "00635134": ("CJ제일", "씨제이제일제당"),
           "01515323": ("엔솔", "LG엔솔", "엘지엔솔", "엘지에너지솔루션")}
GROUPS = {"LG": "01515323", "엘지": "01515323", "CJ": "00635134", "씨제이": "00635134"}
OTHER_ACCOUNTS = ("자본총계", "유동자산", "매출원가", "매출총이익", "판매비와관리비", "현금및현금성자산", "법인세비용차감전순이익",
                  "비유동부채")
OTHER_COMPANIES = ("LG화학", "LG전자", "CJ대한통운", "삼성전자", "카카오", "셀트리온", "SK하이닉스", "현대자동차")
SYNONYMS = {"revenue": "매출", "net_income": "순이익"}
LAST_YEAR, THIS_YEAR = 2025, 2026  # relative years at the reference date
ALIAS_RATE = RELATIVE_RATE = SYNONYM_RATE = 0.3
EXPLICIT_CONSOLIDATED_RATE = 0.25


# ---------------------------------------------------------------- periods

def annual(account: str, year: int) -> dict[str, Any]:
    return {"kind": "instant" if account in BS_ACCOUNTS else "year_to_date", "year": year, "month": 12}


def quarterly(account: str, year: int, month: int) -> dict[str, Any]:
    """The quarter's own period: three months (income), year to date (cash flow), the quarter end (balance sheet)."""
    kind = "instant" if account in BS_ACCOUNTS else "year_to_date" if account == CF_ACCOUNT else "quarter"
    return {"kind": kind, "year": year, "month": month}


def quarters(months: tuple[int, ...], first: int = 2022) -> Iterator[tuple[int, int]]:
    for year in range(first, THIS_YEAR + 1):
        for month in months:
            if year == THIS_YEAR and month not in (3, 6):  # 2026 Q3 and later were not filed at the reference date
                continue
            yield year, month


def prior(period: dict[str, Any]) -> dict[str, Any]:
    return {**period, "year": period["year"] - 1}


# ---------------------------------------------------------------- the grid (section 4.2)

def grid(family: str) -> Iterator[dict[str, Any]]:
    bases = ("CFS", "OFS")
    every = (*IS_ACCOUNTS, CF_ACCOUNT, *BS_ACCOUNTS)
    for corp_code in COMPANIES:
        if family == "A1":
            for fs_div in bases:
                for account in every:
                    for year in range(2022, LAST_YEAR + 1):
                        yield {"kind": "lookup", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "period": annual(account, year)}
        elif family == "A2":
            for fs_div in bases:
                for account in every:
                    for year, month in quarters((3, 6, 9)):
                        yield {"kind": "lookup", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "period": quarterly(account, year, month)}
        elif family == "A3":
            for fs_div in bases:
                for account in (*IS_ACCOUNTS, CF_ACCOUNT):
                    for year in range(2022, LAST_YEAR + 1):
                        current = annual(account, year)
                        yield {"kind": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "current": current, "base": prior(current)}
        elif family == "A4":
            for fs_div in bases:
                for account in IS_ACCOUNTS:
                    for year, month in quarters((3, 6, 9)):
                        current = {"kind": "quarter", "year": year, "month": month}
                        yield {"kind": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "current": current, "base": prior(current)}
        elif family == "A5":
            for fs_div in bases:
                for account in (*IS_ACCOUNTS, CF_ACCOUNT):
                    for year, month in quarters((6, 9)):
                        current = {"kind": "year_to_date", "year": year, "month": month}
                        yield {"kind": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "current": current, "base": prior(current)}
        elif family == "A6":
            for fs_div in bases:
                for account in BS_ACCOUNTS:
                    for year, month in quarters((3, 6, 9), first=2023):
                        current = {"kind": "instant", "year": year, "month": month}
                        yield {"kind": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "current": current, "base": prior(current)}
        elif family == "A7":
            for fs_div in bases:
                for account in BS_ACCOUNTS:
                    for year in range(2022, LAST_YEAR + 1):
                        current = annual(account, year)
                        yield {"kind": "compare", "corp_code": corp_code, "fs_div": fs_div, "account": account,
                               "current": current, "base": prior(current)}
        elif family == "A8":
            for account in every:
                periods = [annual(account, year) for year in range(2022, LAST_YEAR + 1)]
                periods += [quarterly(account, year, month) for year, month in quarters((3, 6, 9))]
                for period in periods:
                    yield {"kind": "side_by_side", "corp_code": corp_code, "account": account, "period": period}
        elif family == "B1":
            for fs_div in bases:
                for account in IS_ACCOUNTS:
                    for year in range(2022, LAST_YEAR + 1):
                        period = {"kind": "quarter", "year": year, "month": 12}
                        base = {"corp_code": corp_code, "fs_div": fs_div, "account": account}
                        yield {"kind": "lookup_not_provided", **base, "period": period}
                        yield {"kind": "compare_not_provided", **base, "current": period, "base": prior(period)}
        elif family == "B2":
            for fs_div in bases:
                for year, month in quarters((6, 9)):
                    period = {"kind": "quarter", "year": year, "month": month}
                    base = {"corp_code": corp_code, "fs_div": fs_div, "account": CF_ACCOUNT}
                    yield {"kind": "lookup_not_provided", **base, "period": period}
                    yield {"kind": "compare_not_provided", **base, "current": period, "base": prior(period)}
        elif family == "B3":
            for fs_div in bases:
                for account in every:
                    period = annual(account, 2014)
                    base = {"corp_code": corp_code, "fs_div": fs_div, "account": account}
                    yield {"kind": "lookup_no_data", **base, "period": period}
                    yield {"kind": "compare_no_data", **base, "current": period, "base": prior(period)}
        elif family == "B4":
            for term in OTHER_ACCOUNTS:
                for year in (2024, LAST_YEAR):
                    yield {"kind": "out_of_scope", "action": "out_of_scope", "corp_code": corp_code,
                           "company": COMPANIES[corp_code], "scope": "account", "term": term, "year": year}
        elif family == "B6":
            for year in (2023, 2024, LAST_YEAR):
                current = {"kind": "year_to_date", "year": year, "month": 12}
                yield {"kind": "clarify_account", "corp_code": corp_code, "fs_div": "CFS", "current": current,
                       "base": prior(current), "form": "compare"}
                yield {"kind": "clarify_account", "corp_code": corp_code, "fs_div": "CFS", "period": current, "form": "lookup"}
        elif family == "B8":
            for other in COMPANIES:
                if other > corp_code:
                    for account in every:
                        yield {"kind": "out_of_scope", "action": "out_of_scope", "corp_code": corp_code, "other": other,
                               "company": f"{COMPANIES[corp_code]}, {COMPANIES[other]}", "scope": "companies",
                               "account": account, "year": LAST_YEAR}
            for pair in (("revenue", "operating_income"), ("operating_income", "net_income"), BS_ACCOUNTS):
                yield {"kind": "out_of_scope", "action": "out_of_scope", "corp_code": corp_code,
                       "company": COMPANIES[corp_code], "scope": "accounts", "accounts": list(pair), "year": LAST_YEAR}
    if family == "B5":
        for name in OTHER_COMPANIES:
            for account in every:
                for year in (2024, LAST_YEAR):
                    yield {"kind": "out_of_scope", "action": "out_of_scope", "company": name, "scope": "company",
                           "account": account, "year": year}
    if family == "B7":
        for group, corp_code in GROUPS.items():
            for account in every:
                for year in (2024, LAST_YEAR):
                    yield {"kind": "clarify_company", "action": "clarify_company", "company": group,
                           "options": [COMPANIES[corp_code]], "account": account, "year": year}


# ---------------------------------------------------------------- wording (section 4.3)

def _batchim(word: str) -> bool:
    last = word.rstrip()[-1]
    if "가" <= last <= "힣":
        return (ord(last) - 0xAC00) % 28 != 0
    if last.isdigit():
        return last in "0136780"  # 영, 일, 삼, 육, 칠, 팔, 십 (공 for 0 reads as 영)
    return False  # Latin initials as read (NAVER, LG, CJ) end in a vowel sound


def josa(word: str, pair: str) -> str:
    with_final, without = pair.split("/")
    return word + (with_final if _batchim(word) else without)


def year_text(year: int, relative: bool) -> str:
    if relative and year == LAST_YEAR:
        return "작년"
    if relative and year == LAST_YEAR - 1:
        return "재작년"
    if relative and year == THIS_YEAR:
        return "올해"
    return f"{year}년"


def period_text(period: dict[str, Any], relative: bool) -> str:
    kind, month = period["kind"], period["month"]
    year = year_text(period["year"], relative)
    quarter = month // 3
    if kind == "quarter":  # three months, including the fourth quarter (B1)
        return f"{year} {quarter}분기"
    if month == 12:
        return f"{year} 말" if kind == "instant" else year
    if kind == "instant":
        return f"{year} {quarter}분기말"
    if month == 3:  # the first quarter's year to date is its three months
        return f"{year} {quarter}분기"
    return f"{year} 상반기" if month == 6 else f"{year} 3분기 누적"


def relative_possible(period: dict[str, Any]) -> bool:
    year = period["year"]
    return year in (LAST_YEAR - 1, LAST_YEAR) if period["month"] == 12 else year in (LAST_YEAR, THIS_YEAR)


TEMPLATES: dict[str, tuple[str, ...]] = {
    "lookup": ("{c} {b}{p} {a} 알려줘.", "{c}의 {b}{p} {a_eun} 얼마야?", "{p} {c} {b}{a} 얼마였어?", "{c} {b}{p} {a} 조회해 줘."),
    "A3": ("{c} {b}{p} {a_i} 전년보다 얼마나 변했어?", "{c}의 {b}{p} {a_eul} 전년과 비교해 줘.",
           "{p} {c} {b}{a}, 전년 대비 어떻게 됐어?"),
    "A4": ("{c} {b}{p} {a_eul} 전년 같은 분기와 비교해 줘.", "{c}의 {b}{p} {a_i} 전년 같은 분기보다 얼마나 변했어?",
           "{p} {c} {b}{a}, 전년 동기 대비 어떻게 됐어?"),
    "A5": ("{c} {b}{p} {a_eul} 전년 같은 기간과 비교해 줘.", "{c}의 {b}{p} {a_i} 전년 동기보다 얼마나 변했어?",
           "{p} {c} {b}{a}, 전년 대비 어떻게 됐어?"),
    "A6": ("{c} {b}{p} {a_eul} 전년 같은 분기말과 비교해 줘.", "{c}의 {b}{p} {a_i} 1년 전보다 얼마나 변했어?",
           "{p} {c} {b}{a}, 전년 같은 시점 대비 어떻게 됐어?"),
    "A7": ("{c} {b}{p} {a_eul} 전년 말과 비교해 줘.", "{c}의 {b}{p} {a_i} 1년 전보다 얼마나 변했어?",
           "{p} {c} {b}{a}, 전년 말 대비 어떻게 됐어?"),
    "A8": ("{c} {p} 연결 {a_irang} 별도 {a} 보여줘.", "{c}의 {p} {a_eul} 연결과 별도로 나란히 보여줘.",
           "{p} {c} {a}, 연결 기준과 별도 기준 둘 다 알려줘."),
    "B_lookup": ("{c} {b}{p} {a} 알려줘.", "{c}의 {b}{p} {a_eun} 얼마야?"),
    "B_compare": ("{c} {b}{p} {a_eul} 전년 같은 분기와 비교해 줘.", "{c}의 {b}{p} {a_i} 전년 같은 분기보다 얼마나 변했어?"),
    "B3_compare": ("{c} {b}{p} {a_i} 전년보다 얼마나 변했어?", "{c}의 {b}{p} {a_eul} 전년과 비교해 줘."),
    "B4": ("{c} {y} {t} 알려줘.", "{c}의 {y} {t_eun} 얼마야?"),
    "B5": ("{n} {y} {a} 알려줘.", "{n}의 {y} {a_eun} 얼마야?"),
    "B6_compare": ("{c} {y} 이익이 얼마나 늘었어?", "{c}의 {y} 이익을 전년과 비교해 줘."),
    "B6_lookup": ("{c} {y} 이익 알려줘.", "{c}의 {y} 이익은 얼마야?"),
    "B7": ("{g} {y} {a} 알려줘.", "{g}의 {y} {a_eun} 얼마야?"),
    "B8_companies": ("{c1_wa} {c2}의 {y} {a} 비교해 줘.", "{c1_irang} {c2} {y} {a_eun} 어디가 더 많아?"),
    "B8_accounts": ("{c} {y} {a1_irang} {a2} 둘 다 알려줘.", "{c}의 {y} {a1_gwa} {a2_eul} 함께 알려줘."),
}


def template_key(family: str, item: dict[str, Any]) -> str:
    if family in ("A1", "A2"):
        return "lookup"
    if family in ("B1", "B2"):
        return "B_lookup" if item["kind"] == "lookup_not_provided" else "B_compare"
    if family == "B3":
        return "B_lookup" if item["kind"] == "lookup_no_data" else "B3_compare"
    if family == "B6":
        return f"B6_{item['form']}"
    if family == "B8":
        return f"B8_{item['scope']}"
    return family


def words(account_phrase: str, name: str = "a") -> dict[str, str]:
    return {name: account_phrase, f"{name}_eun": josa(account_phrase, "은/는"), f"{name}_eul": josa(account_phrase, "을/를"),
            f"{name}_i": josa(account_phrase, "이/가"), f"{name}_irang": josa(account_phrase, "이랑/랑"),
            f"{name}_gwa": josa(account_phrase, "과/와")}


def write(family: str, item: dict[str, Any], rng: random.Random) -> tuple[str, dict[str, Any]]:
    """The question text and the variants drawn for it."""
    choice: dict[str, Any] = {}
    corp_code = item.get("corp_code")
    company = COMPANIES.get(corp_code, "")
    if corp_code in ALIASES and family != "B8" and rng.random() < ALIAS_RATE:
        company = rng.choice(ALIASES[corp_code])
        choice["alias"] = company
    period = item.get("period") or item.get("current")
    relative = bool(period) and relative_possible(period) and family not in ("B3",) and rng.random() < RELATIVE_RATE
    if relative:
        choice["relative_year"] = True
    account = item.get("account")
    phrase = ACCOUNTS[account].label if account else ""
    if account in SYNONYMS and rng.random() < SYNONYM_RATE:
        phrase = SYNONYMS[account]
        choice["synonym"] = phrase
    basis = ""
    if item.get("fs_div") == "OFS":
        basis = "별도 기준 "
    elif item.get("fs_div") == "CFS" and family not in ("B6",) and rng.random() < EXPLICIT_CONSOLIDATED_RATE:
        basis = "연결 기준 "
        choice["explicit_basis"] = True
    fields = {"c": company, "b": basis, **(words(phrase) if phrase else {})}
    if period:
        fields["p"] = period_text(period, relative)
    if "year" in item:
        fields["y"] = year_text(item["year"], relative=False)
    if family == "B6":
        fields["y"] = year_text(period["year"], relative)
    if family == "B4":
        fields.update(words(item["term"], "t"))
    if family == "B5":
        fields["n"] = item["company"]
    if family == "B7":
        fields["g"] = item["company"]
    if family == "B8" and item["scope"] == "companies":
        first, second = COMPANIES[item["corp_code"]], COMPANIES[item["other"]]
        fields.update(c1_wa=josa(first, "과/와"), c1_irang=josa(first, "이랑/랑"), c2=second)
    if family == "B8" and item["scope"] == "accounts":
        fields.update(words(ACCOUNTS[item["accounts"][0]].label, "a1"))
        fields.update(words(ACCOUNTS[item["accounts"][1]].label, "a2"))
    options = TEMPLATES[template_key(family, item)]
    index = rng.randrange(len(options))
    choice["template"] = f"{template_key(family, item)}#{index}"
    return options[index].format(**fields), choice


# ---------------------------------------------------------------- draw (section 4.1)

def spread_unit(family: str, item: dict[str, Any]) -> str:
    """What a family's count is spread evenly over: the company, or for B5 the out-of-scope company name and for
    B7 the group name, which have no company of their own (contract section 4.1; Codex 3-5 review 4)."""
    return item["company"] if family in ("B5", "B7") else item["corp_code"]


def quota(count: int, groups: list[str]) -> dict[str, int]:
    share, extra = divmod(count, len(groups))
    return {group: share + (1 if index < extra else 0) for index, group in enumerate(groups)}


def generate(client: DartClient) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(SEED)
    questions, excluded = [], []
    with using_company_set("sealed-3-1"):
        for family, (count, label) in FAMILIES.items():
            usable: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for item in grid(family):
                try:
                    usable.append((item, expectation(client, item)))
                except Excluded as reason:
                    excluded.append({"family": family, "grid": item, "reason": str(reason)})
            by_company: dict[str, list] = {}
            for pair in usable:
                by_company.setdefault(spread_unit(family, pair[0]), []).append(pair)
            drawn = []
            for group, number in quota(count, sorted(by_company)).items():
                pool = by_company[group]
                if number > len(pool):
                    raise GoldError(f"{family}: {number} wanted from {len(pool)} usable combinations for {group}")
                drawn += rng.sample(pool, number)
            for index, (item, expected) in enumerate(drawn, 1):
                text, choice = write(family, item, rng)
                questions.append({"id": f"{family}-{index:03d}", "bundle": family, "author": "template", "question": text,
                                  "case_types": [label], "tags": tags(expected), "template": choice, "grid": item,
                                  "expected": expected})
    spec = {"version": VERSION, "about": "docs/EVAL_CONTRACT_3-5.ko.md; generated by eval/build_template_questions.py",
            "contract": "3-5", "freeze": "eval/freeze_3-5.json", "reference_date": REFERENCE_DATE, "seed": SEED,
            "gold": "eval/template_3-5/gold.json", "review": REVIEW_POLICY, "questions": questions}
    counts = Counter(entry["family"] for entry in excluded)
    exclusions = {"about": "contract section 4.1 step 2: combinations the gold rules cannot name one usable cell for",
                  "counts": dict(sorted(counts.items())), "items": excluded}
    return spec, exclusions


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    client = DartClient(ResponseCache(CACHE), key_loader=no_key, offline=True)
    spec, exclusions = generate(client)
    texts = {QUESTIONS: render(spec), EXCLUDED: render(exclusions)}
    if args.check:
        stale = [path.name for path, text in texts.items() if not path.exists() or path.read_text(encoding="utf-8") != text]
        print(f"{len(spec['questions'])} questions, {len(exclusions['items'])} excluded combinations; "
              + (f"STALE: {stale}" if stale else "files up to date"))
        return 1 if stale or client.network_requests else 0
    FOLDER.mkdir(parents=True, exist_ok=True)
    for path, text in texts.items():
        path.write_text(text, encoding="utf-8")
    print(f"{len(spec['questions'])} questions -> {QUESTIONS.relative_to(ROOT)}; "
          f"{len(exclusions['items'])} excluded combinations {exclusions['counts']}")
    return 0 if client.network_requests == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
