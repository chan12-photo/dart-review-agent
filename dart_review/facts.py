"""Turn one cached OpenDART response into a traceable amount (a Fact)."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .accounts import AMBIGUOUS, ACCOUNTS, resolve_account
from .client import NO_DATA, DartResponse
from .periods import Period, Source, column_periods

_AMOUNT = re.compile(r"-?\d+")


class UnexpectedAmount(ValueError):
    pass


def parse_amount(text: Any) -> int | None:
    """OpenDART amounts are integer strings; empty or "-" means no value."""
    if text is None:
        return None
    cleaned = str(text).replace(",", "").strip()
    if cleaned in ("", "-"):
        return None
    if not _AMOUNT.fullmatch(cleaned):
        raise UnexpectedAmount(f"unexpected amount format: {text!r}")
    return int(cleaned)


@dataclass(frozen=True)
class Fact:
    """One amount, with everything needed to trace it back to the filing."""

    corp_code: str
    fs_div: str
    account_key: str
    source: Source
    period: Period
    amount: int | None
    currency: str | None
    rcept_no: str | None
    sj_div: str | None
    account_id: str | None
    account_nm: str | None
    resolved_by: str
    notes: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.amount is not None


def fact_from_response(response: DartResponse, account_key: str, column: str) -> Fact:
    """Read ``column`` of the target account from a ``fnlttSinglAcntAll`` response.

    The period comes from the explicit column map, never from the column name.
    """
    if response.endpoint != "fnlttSinglAcntAll.json":
        raise ValueError(f"not a financial statement response: {response.endpoint}")
    params = response.params
    corp_code, fs_div = params["corp_code"], params["fs_div"]
    year, report_code = int(params["bsns_year"]), params["reprt_code"]
    account = ACCOUNTS[account_key]
    source = Source(year, report_code, column)
    # every statement an account may live in shares the same column map, so
    # the period is known before the row is found
    columns = column_periods(year, report_code, account.statements[0])
    if column not in columns:
        raise ValueError(f"{column} is not a {account.statements[0]} column of report {report_code}")
    period = columns[column]

    def missing(resolved_by: str, *notes: str, **found: Any) -> Fact:
        return Fact(corp_code, fs_div, account_key, source, period, None, found.get("currency"), found.get("rcept_no"),
                    found.get("sj_div"), found.get("account_id"), found.get("account_nm"), resolved_by, notes)

    if response.status == NO_DATA:
        return missing("no_data", f"OpenDART 013: {year}년 {report_code} {fs_div} 데이터 없음")
    rows = response.json().get("list", [])
    for row in rows:
        if (row.get("corp_code"), row.get("bsns_year"), row.get("reprt_code")) != (corp_code, str(year), report_code):
            raise ValueError("response rows do not match the request parameters")
    resolution = resolve_account(rows, account_key)
    if resolution.row is None:
        return missing(resolution.method, *resolution.notes)
    row = resolution.row
    if column_periods(year, report_code, row["sj_div"])[column] != period:
        raise AssertionError("statements of one account must share a column map")
    found = {name: row.get(name) for name in ("currency", "rcept_no", "sj_div", "account_id", "account_nm")}
    if f"{column}_amount" not in row:
        return missing(resolution.method, *resolution.notes, f"{column} 칸이 없음", **found)
    amount = parse_amount(row[f"{column}_amount"])
    notes = resolution.notes if amount is not None else resolution.notes + (f"{column} 칸이 비어 있음",)
    return Fact(corp_code, fs_div, account_key, source, period, amount, found["currency"], found["rcept_no"],
                found["sj_div"], found["account_id"], found["account_nm"], resolution.method, notes)


def is_ambiguous(fact: Fact) -> bool:
    return fact.resolved_by == AMBIGUOUS
