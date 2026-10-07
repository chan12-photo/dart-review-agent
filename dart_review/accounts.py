"""The six target accounts and how to find each one in a report.

Resolution order:
1. The standard account id, in the account's statements in order of
   preference (IS before CIS: some companies, such as Kakao, have no separate
   income statement and report revenue in the comprehensive income statement).
2. Only when no row carries the id: an exact (whitespace-insensitive) match on
   a known account name. Kakao's 2023 quarterly reports label revenue
   "영업수익" but tag it ``ifrs-full_GrossProfit``, so the id alone misses it.

Rows whose ``account_detail`` is not "-" are breakdowns (statement of changes
in equity components) and are never used. More than one matching row in the
same statement is ambiguous and is not resolved automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Sequence

NON_STANDARD_ID = "-표준계정코드 미사용-"
ID = "account_id"
NAME = "account_name"
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


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


@dataclass(frozen=True)
class Resolution:
    account: Account
    method: str  # ID, NAME, AMBIGUOUS, or NOT_FOUND
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
            note = f"표준계정ID {account.account_id} 없음: 계정명 '{row.get('account_nm')}'으로 찾음"
            if row.get("account_id") not in (NON_STANDARD_ID, "", None):
                note += f" (이 행의 ID는 {row.get('account_id')}로 표기됨)"
            return Resolution(account, NAME, row, notes=(note,))
        if hits:
            return _ambiguous(account, hits)
    return Resolution(account, NOT_FOUND, None, notes=(f"{account.label} 계정을 찾지 못함",))


def _ambiguous(account: Account, hits: list[dict[str, Any]]) -> Resolution:
    described = ", ".join(f"{row.get('sj_div')} '{row.get('account_nm')}'" for row in hits)
    return Resolution(account, AMBIGUOUS, None, tuple(hits), (f"{account.label} 후보가 여러 개다: {described}",))
