"""Find the numbers in a Korean answer and check each one against what the model was shown.

A written number is grounded when it is an allowed number rounded (half up)
or truncated at the precision it is written at: "333.6조" is written to 0.1조,
so it matches 333,605,938,000,000 (rounded) but "333.7조" matches nothing.
The sign is ignored because a decrease is often written as a word ("감소").

Kinds of numbers (docs/EVAL_DESIGN.ko.md section 4):
- amount: written with 조/억/만 (optionally 천/백/십 within a group) and/or
  원, or a bare number of 1,000 or more / with thousands separators
- percent: "%", "퍼센트" (grounded only by rates)
- point: "%p", "퍼센트포인트" (grounded only by percentage-point figures)
- ratio: "배" (grounded only by multiples)
  Tool results give no points or multiples, so a self-computed one is ungrounded.
- year: "2025년", dates, bare 19xx/20xx; must be an allowed year
- receipt: a 14-digit number not followed by 원; an allowed receipt number, or
  exactly an allowed amount written without separators
- calendar: months, days, quarters, month counts, fiscal terms; accepted
  within their ranges (whether the period is right is checked by people,
  EVAL_DESIGN section 3)
- unparsed: a magnitude word or date this module cannot read, or a bare
  decimal; never grounded

What may ground a number: only tool results that succeeded (a result with an
"error" key grounds nothing, so a model cannot launder a number through an
error message), and years from the question.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
import re
from typing import Any, Iterable

UNITS = {"조": Decimal(10) ** 12, "억": Decimal(10) ** 8, "만": Decimal(10) ** 4}
MULTIPLIERS = {"천": 1000, "백": 100, "십": 10}
NEGATIVE = "-−△"
_NUM = r"\d[\d,]*(?:\.\d+)?"
# "원" that starts a word such as 원인, 원래, 원본, 원가, 원칙 is not the currency
_NOT_WORD = r"(?![인래본가칙])"


@dataclass(frozen=True)
class Mention:
    kind: str
    text: str
    value: Decimal | None = None
    unit: Decimal | None = None  # precision of the written number (one unit of its last digit)
    extra: tuple = ()


@dataclass
class Allowed:
    amounts: set[Decimal] = field(default_factory=set)
    percents: set[Decimal] = field(default_factory=set)
    points: set[Decimal] = field(default_factory=set)
    ratios: set[Decimal] = field(default_factory=set)
    years: set[int] = field(default_factory=set)
    receipts: set[str] = field(default_factory=set)


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _precision(text: str) -> Decimal:
    digits = text.split(".")[1] if "." in text else ""
    return Decimal(1).scaleb(-len(digits))


def _group(name: str, unit: str) -> str:
    return rf"(?:(?P<{name}>{_NUM})\s*(?P<{name}_k>[천백십])?\s*{unit}\s*)?"


_KOREAN_AMOUNT = re.compile(
    rf"(?P<sign>[{NEGATIVE}]\s*)?"
    rf"(?=\d[\d,]*(?:\.\d+)?\s*[천백십]?\s*[조억만])"
    + _group("jo", "조") + _group("eok", "억") + _group("man", "만")
    + rf"(?:(?P<won>\d[\d,]*)\s*(?=원{_NOT_WORD}))?"
    rf"(?:원{_NOT_WORD})?"
)
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("receipt", re.compile(rf"(?<!\d)\d{{14}}(?!\d)(?!\s*원{_NOT_WORD})")),
    ("date", re.compile(r"(?<!\d)(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?!\d)")),
    ("compact_date", re.compile(rf"(?<![\d,])(\d{{4}})(\d{{2}})(\d{{2}})(?![\d,])(?!\s*원{_NOT_WORD})")),
    ("percent", re.compile(rf"([{NEGATIVE}+]\s*)?({_NUM})\s*(%p|%|퍼센트포인트|퍼센트)")),
    ("ratio", re.compile(rf"({_NUM})\s*배")),
    ("korean_amount", _KOREAN_AMOUNT),
    ("won", re.compile(rf"([{NEGATIVE}]\s*)?(\d[\d,]*)\s*원{_NOT_WORD}")),
    ("year", re.compile(r"(?<!\d)(\d{4})\s*년")),
    ("calendar", re.compile(r"(?<!\d)(\d{1,2})\s*(월|일|분기|개월)|제\s*(\d{1,3})\s*기|(?<!\d)(\d{1,2})\s*[~∼]\s*(\d{1,2})\s*월")),
    ("magnitude", re.compile(rf"{_NUM}\s*[천백십조억만]")),  # a magnitude the amount pattern could not read
    ("bare", re.compile(rf"([{NEGATIVE}]\s*)?({_NUM})")),
]


def _valid_date(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def extract(text: str) -> list[Mention]:
    """Every number in ``text``, classified. Matched spans are blanked so nothing is counted twice."""
    remaining = text or ""
    mentions: list[Mention] = []
    for kind, pattern in _PATTERNS:
        found: list[tuple[int, int]] = []
        for match in pattern.finditer(remaining):
            if not re.search(r"\d", match.group(0)):
                continue
            mention = _classify(kind, match)
            if mention is None:
                continue
            mentions.extend(mention)
            found.append(match.span())
        for start, end in found:
            remaining = remaining[:start] + " " * (end - start) + remaining[end:]
    return mentions


def _date_mentions(text: str, year: int, month: int, day: int) -> list[Mention]:
    return [Mention("year", text, Decimal(year)), Mention("calendar", text, extra=("month", month)),
            Mention("calendar", text, extra=("day", day))]


def _classify(kind: str, match: re.Match[str]) -> list[Mention] | None:
    text = match.group(0).strip()
    if kind == "receipt":
        return [Mention("receipt", text, Decimal(text), Decimal(1), extra=(text,))]
    if kind in ("date", "compact_date"):
        year, month, day = (int(group) for group in match.groups())
        if _valid_date(year, month, day) and 1990 <= year <= 2100:
            return _date_mentions(text, year, month, day)
        return [Mention("unparsed", text)] if kind == "date" else None  # an 8-digit non-date is left to other kinds
    if kind == "percent":
        suffix = match.group(3)
        return [Mention("point" if suffix in ("%p", "퍼센트포인트") else "percent", text, _decimal(match.group(2)),
                        _precision(match.group(2)), extra=(suffix,))]
    if kind == "ratio":
        return [Mention("ratio", text, _decimal(match.group(1)), _precision(match.group(1)))]
    if kind == "korean_amount":
        total, unit = Decimal(0), None
        for name, word in (("jo", "조"), ("eok", "억"), ("man", "만")):
            number = match.group(name)
            if number is None:
                continue
            scale = UNITS[word] * MULTIPLIERS.get(match.group(f"{name}_k") or "", 1)
            total += _decimal(number) * scale
            unit = _precision(number) * scale
        if match.group("won"):
            total += _decimal(match.group("won"))
            unit = Decimal(1)
        return [Mention("amount", text, total, unit)]
    if kind == "won":
        return [Mention("amount", text, _decimal(match.group(2)), Decimal(1))]
    if kind == "year":
        return [Mention("year", text, Decimal(int(match.group(1))))]
    if kind == "calendar":
        if match.group(2):
            return [Mention("calendar", text, extra=({"월": "month", "일": "day", "분기": "quarter", "개월": "months"}[match.group(2)],
                                                     int(match.group(1))))]
        if match.group(3):
            return [Mention("calendar", text, extra=("term", int(match.group(3))))]
        return [Mention("calendar", text, extra=("month", int(match.group(4)))),
                Mention("calendar", text, extra=("month", int(match.group(5))))]
    if kind == "magnitude":
        return [Mention("unparsed", text)]
    number = match.group(2)
    if "." in number:
        return [Mention("unparsed", text)]
    value = _decimal(number)
    if "," not in number and 1900 <= value <= 2100 and len(number) == 4:
        return [Mention("year", text, value)]
    if "," in number or value >= 1000:
        return [Mention("amount", text, value, Decimal(1))]
    return []  # a small count such as "2개"


_CALENDAR_RANGES = {"month": (1, 12), "day": (1, 31), "quarter": (1, 4), "months": (1, 12), "term": (1, 200)}


def _written_as(value: Decimal, allowed: Decimal, unit: Decimal) -> bool:
    """Whether ``value`` is ``allowed`` rounded half up or truncated at ``unit`` (absolute values)."""
    value, allowed = abs(value), abs(allowed)
    steps = allowed / unit
    return any(steps.to_integral_value(rounding=mode) * unit == value for mode in (ROUND_HALF_UP, ROUND_DOWN))


def grounded(mention: Mention, allowed: Allowed) -> bool:
    if mention.kind == "amount":
        return any(_written_as(mention.value, amount, mention.unit) for amount in allowed.amounts)
    if mention.kind in ("percent", "point", "ratio"):
        pool = {"percent": allowed.percents, "point": allowed.points, "ratio": allowed.ratios}[mention.kind]
        return any(_written_as(mention.value, rate, mention.unit) for rate in pool)
    if mention.kind == "year":
        return int(mention.value) in allowed.years
    if mention.kind == "receipt":
        return mention.extra[0] in allowed.receipts or mention.value in allowed.amounts
    if mention.kind == "calendar":
        low, high = _CALENDAR_RANGES[mention.extra[0]]
        return low <= mention.extra[1] <= high
    return False


def allowed_from(*sources: Any) -> Allowed:
    """Every number in tool results (nested JSON-like data). A dict with an "error" key contributes nothing."""
    allowed = Allowed()
    for source in sources:
        _collect(source, allowed, key=None)
    return allowed


def question_years(question: str) -> set[int]:
    """The question may ground years only; an amount or rate in a question is the user's claim, not evidence."""
    return {int(mention.value) for mention in extract(question) if mention.kind == "year"}


def _collect(value: Any, allowed: Allowed, key: str | None) -> None:
    if isinstance(value, dict):
        if "error" in value:
            return
        for name, item in value.items():
            _collect(item, allowed, name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, allowed, key)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int):
        allowed.amounts.add(abs(Decimal(value)))
        if 1900 <= value <= 2100:
            allowed.years.add(value)
    elif isinstance(value, str):
        if key in ("change_pct", "rate") and _is_rate(value):
            allowed.percents.add(abs(Decimal(value)))
            return
        for mention in extract(value):
            if mention.kind == "amount":
                allowed.amounts.add(abs(mention.value))
            elif mention.kind in ("percent", "point", "ratio"):
                {"percent": allowed.percents, "point": allowed.points, "ratio": allowed.ratios}[mention.kind].add(abs(mention.value))
            elif mention.kind == "year":
                allowed.years.add(int(mention.value))
            elif mention.kind == "receipt":
                allowed.receipts.add(mention.extra[0])


def _is_rate(text: str) -> bool:
    try:
        Decimal(text)
    except InvalidOperation:
        return False
    return True


@dataclass(frozen=True)
class Check:
    mention: Mention
    grounded: bool


def check_text(text: str, allowed: Allowed) -> list[Check]:
    return [Check(mention, grounded(mention, allowed)) for mention in extract(text)]


def ungrounded(checks: Iterable[Check]) -> list[Mention]:
    return [check.mention for check in checks if not check.grounded]
