"""Comparability rules: decide whether two amounts may be compared, then compare them.

Statuses (docs/SCOPE.ko.md section 3), checked in this order:
- 비교 불가: different company, account, consolidated/separate basis, period
  kind or length, or a known currency mismatch. Never computed.
- 확인 필요 (no change computed): the account matched more than one row.
- 데이터 없음: a value is missing (no report, no row, or an empty column).
- 확인 필요 (change computed, with the reasons): something the comparison
  depends on could not be confirmed. The two values come from different
  reports and the check of a shared basis found a restatement or could not be
  completed; the account was matched by a name that conflicts with the row's
  standard id; or a currency is missing.
- 비교 가능: the change is computed and nothing above applies. For two
  reports this means the values they both present agree as far as they could
  be observed, not that a restatement is impossible.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from .accounts import ACCOUNTS, NAME, NAME_CONFLICT
from .facts import Fact, is_ambiguous
from .periods import period_issues

COMPARABLE = "비교 가능"
NOT_COMPARABLE = "비교 불가"
NO_DATA = "데이터 없음"
NEEDS_REVIEW = "확인 필요"
FS_NAMES = {"CFS": "연결", "OFS": "별도"}


@dataclass(frozen=True)
class Restatement:
    """The same value (company, basis, account, period, currency) presented differently by two reports."""

    earlier: Fact
    later: Fact

    @property
    def difference(self) -> int:
        return self.later.amount - self.earlier.amount

    def describe(self) -> str:
        return (f"{self.earlier.period.label()} 값이 보고서마다 다르다(재작성): 접수번호 {self.earlier.rcept_no}에서 "
                f"{self.earlier.amount:,}, 접수번호 {self.later.rcept_no}에서 {self.later.amount:,}")


def value_key(fact: Fact) -> tuple:
    return (fact.corp_code, fact.fs_div, fact.account_key, fact.period, fact.currency)


def find_restatements(facts: Iterable[Fact]) -> list[Restatement]:
    """Pairs of available facts for the same value whose amounts differ between reports."""
    by_key: dict[tuple, list[Fact]] = {}
    for fact in facts:
        if fact.available:
            by_key.setdefault(value_key(fact), []).append(fact)
    found = []
    for group in by_key.values():
        group.sort(key=lambda fact: fact.rcept_no or "")
        for earlier, later in zip(group, group[1:]):
            if earlier.rcept_no != later.rcept_no and earlier.amount != later.amount:
                found.append(Restatement(earlier, later))
    return found


@dataclass(frozen=True)
class BasisCheck:
    """What could be observed about whether the reports behind a comparison share a basis.

    ``linked``: the two reports are connected by values they (or reports in
    between) both present, and those values agree. ``gaps``: reports or values
    the check needed but could not use.
    """

    restatements: tuple[Restatement, ...] = ()
    linked: bool = False
    gaps: tuple[str, ...] = ()


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
    if current.currency and base.currency and current.currency != base.currency:
        issues.append(f"통화가 다르다 ({current.currency}, {base.currency})")
    return issues


def basis_review(current: Fact, base: Fact, check: BasisCheck | None) -> tuple[list[str], list[str]]:
    """(reasons for review, notes) about whether the two values share a basis."""
    if current.rcept_no == base.rcept_no:
        # one report presents both values on the same basis; an earlier report's
        # different figure for the base period is worth noting, not a problem
        notes = [item.describe() + " (이 비교는 같은 보고서의 값을 쓴다)" for item in (check.restatements if check else ())
                 if item.later.rcept_no == base.rcept_no and item.later.period == base.period]
        return [], notes
    notes = [f"서로 다른 보고서의 값이다 (접수번호 {current.rcept_no}, {base.rcept_no})"]
    if check is None:
        return ["두 보고서가 같은 기준으로 작성됐는지 확인하지 않았다"], notes
    if check.restatements:
        return [item.describe() + " (이번 비교 기간에 미친 영향은 확인하지 못했다)" for item in check.restatements], notes
    if not check.linked:
        return list(check.gaps) or ["두 보고서에 함께 나오는 값이 없어 재작성 여부를 확인할 수 없다"], notes
    notes.append("두 보고서를 잇는 값이 모두 일치한다 (관찰한 범위에서 재작성 없음)")
    return [], notes + list(check.gaps)


def compare(current: Fact | None, base: Fact | None, check: BasisCheck | None = None) -> Comparison:
    """Compare ``current`` with the earlier ``base``.

    ``check`` is what ``review.review_change`` observed about the reports
    behind the two values. Without it, values from two different reports are
    never reported as 비교 가능.
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
    review = [note for fact in (current, base) if fact.resolved_by == NAME_CONFLICT for note in fact.notes]
    notes = [note for fact in (current, base) if fact.resolved_by != NAME_CONFLICT for note in fact.notes]
    if NAME in (current.resolved_by, base.resolved_by):
        notes.append("표준계정ID가 아니라 계정명으로 찾은 값이 있다")
    if not (current.currency and base.currency):
        review.append("통화가 확인되지 않았다")
    basis_reasons, basis_notes = basis_review(current, base, check)
    review += basis_reasons
    notes += basis_notes
    change = current.amount - base.amount
    change_pct, direction = _rate_and_direction(current, base)
    if change_pct is None and base.amount <= 0:
        notes.append("기준 값이 0 이하라 변화율을 계산하지 않는다")
    elif change_pct is None:
        notes.append("부호가 바뀌어 변화율을 계산하지 않는다")
    status = NEEDS_REVIEW if review else COMPARABLE
    return Comparison(status, tuple(dict.fromkeys(review)), tuple(dict.fromkeys(notes)), current, base,
                      change, change_pct, direction)


def _rate_and_direction(current: Fact, base: Fact) -> tuple[Decimal | None, str]:
    new, old = current.amount, base.amount
    profit_like = ACCOUNTS[current.account_key].profit_like
    if old > 0 and new >= 0:
        # two decimal places, halves rounded away from zero
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
