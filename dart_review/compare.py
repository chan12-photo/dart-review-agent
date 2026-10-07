"""Comparability rules: decide whether two amounts may be compared, then compare them.

Statuses (docs/SCOPE.ko.md section 3), checked in this order:
- 비교 불가: different company, account, consolidated/separate basis, period
  kind or length, or currency. These comparisons are never computed.
- 확인 필요 (no change computed): the account matched more than one row.
- 데이터 없음: a value is missing (no report, no row, or an empty column).
- 확인 필요 (change computed, with the reason): the two values come from
  different reports and a restatement was filed between them, so they may
  not share a basis.
- 비교 가능: the change is computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence

from .accounts import ACCOUNTS, NAME
from .facts import Fact, is_ambiguous
from .periods import period_issues

COMPARABLE = "비교 가능"
NOT_COMPARABLE = "비교 불가"
NO_DATA = "데이터 없음"
NEEDS_REVIEW = "확인 필요"
FS_NAMES = {"CFS": "연결", "OFS": "별도"}


@dataclass(frozen=True)
class Restatement:
    """The same amount presented differently by two reports."""

    earlier: Fact
    later: Fact

    @property
    def difference(self) -> int:
        return self.later.amount - self.earlier.amount

    def describe(self) -> str:
        return (f"{self.earlier.period.label()} 값이 재작성됨: 접수번호 {self.earlier.rcept_no}에서 "
                f"{self.earlier.amount:,}, 접수번호 {self.later.rcept_no}에서 {self.later.amount:,}")


def _same_value_key(fact: Fact) -> tuple:
    return (fact.corp_code, fact.fs_div, fact.account_key, fact.period)


def find_restatements(facts: Iterable[Fact]) -> list[Restatement]:
    """Pairs of available facts for the same value whose amounts differ between reports."""
    by_key: dict[tuple, list[Fact]] = {}
    for fact in facts:
        if fact.available:
            by_key.setdefault(_same_value_key(fact), []).append(fact)
    found = []
    for group in by_key.values():
        group.sort(key=lambda fact: fact.rcept_no or "")
        for earlier, later in zip(group, group[1:]):
            if earlier.rcept_no != later.rcept_no and earlier.amount != later.amount:
                found.append(Restatement(earlier, later))
    return found


@dataclass(frozen=True)
class Comparison:
    status: str
    reasons: tuple[str, ...]
    notes: tuple[str, ...]
    current: Fact | None
    base: Fact | None
    change: int | None = None
    change_pct: Decimal | None = None
    direction: str | None = None


def structural_issues(current: Fact, base: Fact) -> list[str]:
    issues = []
    if current.corp_code != base.corp_code:
        issues.append("서로 다른 회사의 값이다")
    if current.account_key != base.account_key:
        issues.append(f"서로 다른 계정이다 ({current.account_key}, {base.account_key})")
    if current.fs_div != base.fs_div:
        issues.append(f"{FS_NAMES.get(current.fs_div, current.fs_div)}과 {FS_NAMES.get(base.fs_div, base.fs_div)}"
                      " 기준은 합치거나 비교하지 않는다 (나란히 보여줄 수만 있다)")
    issues.extend(period_issues(current.period, base.period))
    if current.available and base.available and current.currency != base.currency:
        issues.append(f"통화가 다르다 ({current.currency}, {base.currency})")
    return issues


def compare(current: Fact | None, base: Fact | None, restatements: Sequence[Restatement] = ()) -> Comparison:
    """Compare ``current`` with the earlier ``base``.

    ``restatements`` come from ``find_restatements``. When both values come
    from one report they share a basis, and a restatement of the base value is
    only noted. When they come from two reports, a restatement filed between
    the two makes the result 확인 필요.
    """
    if current is None or base is None:
        return Comparison(NO_DATA, ("값을 찾을 수 있는 보고서가 없다",), (), current, base)
    issues = structural_issues(current, base)
    if issues:
        return Comparison(NOT_COMPARABLE, tuple(issues), (), current, base)
    ambiguous = [note for fact in (current, base) if is_ambiguous(fact) for note in fact.notes]
    if ambiguous:
        return Comparison(NEEDS_REVIEW, tuple(ambiguous), (), current, base)
    missing = [note for fact in (current, base) if not fact.available
               for note in (fact.notes or (f"{fact.period.label()} 값이 없다",))]
    if missing:
        return Comparison(NO_DATA, tuple(dict.fromkeys(missing)), (), current, base)
    notes = list(current.notes + base.notes)
    if current.resolved_by == NAME or base.resolved_by == NAME:
        notes.append("표준계정ID가 아니라 계정명으로 찾은 값이 있다")
    review = []
    relevant = [item for item in restatements if _same_value_key(item.later)[:3] == _same_value_key(current)[:3]]
    if current.rcept_no == base.rcept_no:
        notes += [item.describe() + " (이 비교는 재작성된 값을 쓴다)" for item in relevant
                  if item.later.period == base.period and item.later.rcept_no == base.rcept_no]
    else:
        notes.append(f"서로 다른 보고서의 값이다 (접수번호 {current.rcept_no}, {base.rcept_no})")
        # a restatement filed between the two reports means they may not share a basis
        first, last = sorted((base.rcept_no or "", current.rcept_no or ""))
        review += [item.describe() + " (두 보고서 사이에 기준이 바뀌었을 수 있다)" for item in relevant
                   if (item.earlier.rcept_no or "") < last and (item.later.rcept_no or "") > first]
    change = current.amount - base.amount
    change_pct, direction = _rate_and_direction(current, base)
    if change_pct is None and base.amount <= 0:
        notes.append("기준 값이 0 이하라 변화율을 계산하지 않는다")
    elif change_pct is None:
        notes.append("부호가 바뀌어 변화율을 계산하지 않는다")
    status = NEEDS_REVIEW if review else COMPARABLE
    return Comparison(status, tuple(review), tuple(dict.fromkeys(notes)), current, base, change, change_pct, direction)


def _rate_and_direction(current: Fact, base: Fact) -> tuple[Decimal | None, str]:
    new, old = current.amount, base.amount
    profit_like = ACCOUNTS[current.account_key].profit_like
    if old > 0 and new >= 0:
        pct = (Decimal(new - old) * 100 / Decimal(old)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return pct, "증가" if new > old else "감소" if new < old else "변동 없음"
    if profit_like:
        if old < 0 < new:
            return None, "흑자 전환"
        if old > 0 > new:
            return None, "적자 전환"
        if old < 0 and new < 0:
            return None, "적자 축소" if new > old else "적자 확대" if new < old else "적자 지속"
    return None, "증가" if new > old else "감소" if new < old else "변동 없음"
