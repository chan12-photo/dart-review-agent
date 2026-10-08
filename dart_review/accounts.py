"""The six target accounts and how to find each one in a report.

Resolution order:
1. The standard account id, in the account's statements in order of
   preference (IS before CIS: some companies, such as Kakao, have no separate
   income statement and report revenue in the comprehensive income statement).
2. Only when no row carries the id: an exact (whitespace-insensitive) match on
   a known account name.
   - A row without a standard id (``-표준계정코드 미사용-`` or empty) is accepted.
   - A row tagged with a *different* standard id is a conflict: the name and
     the id disagree about what the row is (for example "당기순이익" tagged as
     profit attributable to owners of the parent). It is returned with method
     NAME_CONFLICT so the comparison asks for review, unless the conflict is
     listed in VERIFIED_MISTAGS with evidence.

Rows whose ``account_detail`` is not "-" are breakdowns (for example segment
or equity-component members) and are never used. More than one matching row
in the same statement is ambiguous and is not resolved automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence

NON_STANDARD_ID = "-표준계정코드 미사용-"
ID = "account_id"
NAME = "account_name"
NAME_CONFLICT = "account_name_conflict"
AMBIGUOUS = "ambiguous"
NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Account:
    key: str
    label: str
    account_id: str
    statements: tuple[str, ...]
    names: tuple[str, ...]
    # profit-like accounts are described as 흑자/적자 when the sign changes
    profit_like: bool = False


# Names are the variants seen in the development cache (docs/DATA_NOTES.ko.md)
# and the account names seen during company selection, before the evaluation
# companies were sealed (docs/SCOPE.ko.md sections 5 and 11).
ACCOUNTS = {
    account.key: account
    for account in (
        Account("revenue", "매출액", "ifrs-full_Revenue", ("IS", "CIS"), ("매출액", "영업수익", "수익(매출액)")),
        Account("operating_income", "영업이익", "dart_OperatingIncomeLoss", ("IS", "CIS"),
                ("영업이익", "영업이익(손실)"), profit_like=True),
        Account("net_income", "당기순이익", "ifrs-full_ProfitLoss", ("IS", "CIS"),
                ("당기순이익", "당기순이익(손실)", "연결당기순이익", "반기순이익", "분기순이익",
                 "분기순이익(손실)"), profit_like=True),
        Account("operating_cash_flow", "영업활동현금흐름", "ifrs-full_CashFlowsFromUsedInOperatingActivities", ("CF",),
                ("영업활동현금흐름", "영업활동으로인한현금흐름")),
        Account("total_assets", "자산총계", "ifrs-full_Assets", ("BS",), ("자산총계",)),
        Account("total_liabilities", "부채총계", "ifrs-full_Liabilities", ("BS",), ("부채총계",)),
    )
}


# (corp_code, account key, the row's standard id, the row's name): conflicts
# checked against the cache and accepted as mis-tags. Evidence in
# docs/DATA_NOTES.ko.md section 3.
VERIFIED_MISTAGS = {
    # Kakao tags its 영업수익 line ifrs-full_Revenue in 18 of its 24 cached
    # responses and ifrs-full_GrossProfit only in the 2023 Q1, half-year, and
    # Q3 reports (consolidated and separate); no other revenue-like line exists.
    ("00258801", "revenue", "ifrs-full_GrossProfit", "영업수익"),
}


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def normalize_term(name: str) -> str:
    """An account name as a term in a question: parenthesized parts removed, Hangul letters only."""
    return re.sub(r"[^가-힣]", "", re.sub(r"\([^)]*\)", "", name or ""))


@dataclass(frozen=True)
class Resolution:
    account: Account
    method: str  # ID, NAME, NAME_CONFLICT, AMBIGUOUS, or NOT_FOUND
    row: dict[str, Any] | None
    candidates: tuple[dict[str, Any], ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def found(self) -> bool:
        return self.row is not None


def _is_total_row(row: dict[str, Any]) -> bool:
    return (row.get("account_detail") or "-") == "-"


def resolve_account(rows: Sequence[dict[str, Any]], key: str) -> Resolution:
    account = ACCOUNTS[key]
    usable = [row for row in rows if _is_total_row(row)]
    for sj_div in account.statements:
        hits = [row for row in usable if row.get("sj_div") == sj_div and row.get("account_id") == account.account_id]
        if len(hits) == 1:
            return Resolution(account, ID, hits[0])
        if hits:
            return _ambiguous(account, hits)
    names = {normalize_name(name) for name in account.names}
    for sj_div in account.statements:
        hits = [row for row in usable if row.get("sj_div") == sj_div and normalize_name(row.get("account_nm", "")) in names]
        if len(hits) == 1:
            row = hits[0]
            row_id, name = row.get("account_id"), row.get("account_nm")
            note = f"표준계정ID {account.account_id} 없음: 계정명 '{name}'으로 찾음"
            if row_id in (NON_STANDARD_ID, "", None):
                return Resolution(account, NAME, row, notes=(note,))
            if (row.get("corp_code"), key, row_id, normalize_name(name)) in VERIFIED_MISTAGS:
                return Resolution(account, NAME, row, notes=(note + f" (이 행의 ID {row_id}는 확인된 오표기)",))
            return Resolution(account, NAME_CONFLICT, row, notes=(
                f"계정명 '{name}'은 {account.label}와 같지만 다른 표준계정ID({row_id})로 표기됨: 같은 계정인지 확인 필요",))
        if hits:
            return _ambiguous(account, hits)
    return Resolution(account, NOT_FOUND, None, notes=(f"{account.label} 계정을 찾지 못함",))


def _ambiguous(account: Account, hits: list[dict[str, Any]]) -> Resolution:
    described = ", ".join(f"{row.get('sj_div')} '{row.get('account_nm')}'" for row in hits)
    return Resolution(account, AMBIGUOUS, None, tuple(hits), (f"{account.label} 후보가 여러 개다: {described}",))
