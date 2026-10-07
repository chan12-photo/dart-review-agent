"""Find the numbers in a Korean answer and check each one against what the model was shown.

A number is grounded when it matches a number from the tool results (or the
question) within the precision it is written at: "333.6조" is written to 0.1조,
so any allowed amount whose absolute value is within 0.1조 of 333.6조
matches. Rounding and truncation are both accepted; the sign is ignored
because a decrease is often written as a word ("감소") rather than "-".

Kinds of numbers (docs/EVAL_DESIGN.ko.md section 4):
- amount: written with 조/억/만 (optionally 천) and/or 원, or a bare number of
  1,000 or more / with thousands separators; must match an allowed amount
- percent: "%", "퍼센트"; must match an allowed rate
- point: "%p", "퍼센트포인트"; must match an allowed percentage-point figure
- ratio: "배"; must match an allowed multiple
  (tool results give no points or multiples, so a self-computed one is
  ungrounded; a rate never grounds a point or a multiple)
- year: "2025년", ISO dates, bare 19xx/20xx; must be an allowed year
- receipt: 14-digit numbers; an allowed receipt number, or exactly an
  allowed amount written without separators
- calendar: months, days, quarters, month counts, fiscal terms; accepted
  within their ranges (whether the period is right is scored separately)
- unparsed: anything else that is not a small integer count; never grounded
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

UNITS = {"조": Decimal(10) ** 12, "억": Decimal(10) ** 8, "만": Decimal(10) ** 4}
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

    def update(self, other: "Allowed") -> None:
        self.amounts |= other.amounts
        self.percents |= other.percents
        self.points |= other.points
        self.ratios |= other.ratios
        self.years |= other.years
        self.receipts |= other.receipts


def _decimal(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


def _precision(text: str) -> Decimal:
    digits = text.split(".")[1] if "." in text else ""
    return Decimal(1).scaleb(-len(digits))


_KOREAN_AMOUNT = re.compile(
    rf"(?P<sign>[{NEGATIVE}]\s*)?"
    rf"(?=\d[\d,]*(?:\.\d+)?\s*천?\s*[조억만])"
    rf"(?:(?P<jo>{_NUM})\s*(?P<jo_k>천)?\s*조\s*)?"
    rf"(?:(?P<eok>{_NUM})\s*(?P<eok_k>천)?\s*억\s*)?"
    rf"(?:(?P<man>{_NUM})\s*(?P<man_k>천)?\s*만\s*)?"
    rf"(?:(?P<won>\d[\d,]*)\s*(?=원{_NOT_WORD}))?"
    rf"(?:원{_NOT_WORD})?"
)
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("receipt", re.compile(r"(?<!\d)\d{14}(?!\d)")),
    ("iso_date", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
    ("percent", re.compile(rf"([{NEGATIVE}+]\s*)?({_NUM})\s*(%p|%|퍼센트포인트|퍼센트)")),
    ("ratio", re.compile(rf"({_NUM})\s*배")),
    ("korean_amount", _KOREAN_AMOUNT),
    ("won", re.compile(rf"([{NEGATIVE}]\s*)?(\d[\d,]*)\s*원{_NOT_WORD}")),
    ("year", re.compile(r"(?<!\d)(\d{4})\s*년")),
    ("calendar", re.compile(r"(?<!\d)(\d{1,2})\s*(월|일|분기|개월)|제\s*(\d{1,3})\s*기|(?<!\d)(\d{1,2})\s*[~∼]\s*(\d{1,2})\s*월")),
    ("bare", re.compile(rf"([{NEGATIVE}]\s*)?({_NUM})")),
]


def extract(text: str) -> list[Mention]:
    """Every number in ``text``, classified. Matched spans are blanked so nothing is counted twice."""
    remaining = text or ""
    mentions: list[Mention] = []
    for kind, pattern in _PATTERNS:
        found: list[tuple[int, int]] = []
        for match in pattern.finditer(remaining):
            if not match.group(0).strip() or not re.search(r"\d", match.group(0)):
                continue
            mention = _classify(kind, match)
            if mention is None:
                continue
            mentions.extend(mention)
            found.append(match.span())
        for start, end in found:
            remaining = remaining[:start] + " " * (end - start) + remaining[end:]
    return mentions


def _classify(kind: str, match: re.Match[str]) -> list[Mention] | None:
    text = match.group(0).strip()
    if kind == "receipt":
        return [Mention("receipt", text, Decimal(text), Decimal(1), extra=(text,))]
    if kind == "iso_date":
        year, month, day = (int(group) for group in match.groups())
        return [Mention("year", text, Decimal(year)), Mention("calendar", text, extra=("month", month)),
                Mention("calendar", text, extra=("day", day))]
    if kind == "percent":
        suffix = match.group(3)
        return [Mention("point" if suffix in ("%p", "퍼센트포인트") else "percent", text, _decimal(match.group(2)),
                        _precision(match.group(2)), extra=(suffix,))]
    if kind == "ratio":
        return [Mention("ratio", text, _decimal(match.group(1)), _precision(match.group(1)))]
    if kind == "korean_amount":
        total, unit = Decimal(0), None
        for name in ("jo", "eok", "man"):
            number = match.group(name)
            if number is None:
                continue
            scale = UNITS[{"jo": "조", "eok": "억", "man": "만"}[name]] * (1000 if match.group(f"{name}_k") else 1)
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


def grounded(mention: Mention, allowed: Allowed) -> bool:
    if mention.kind == "amount":
        return any(abs(abs(mention.value) - amount) < mention.unit for amount in allowed.amounts)
    if mention.kind in ("percent", "point", "ratio"):
        pool = {"percent": allowed.percents, "point": allowed.points, "ratio": allowed.ratios}[mention.kind]
        return any(abs(abs(mention.value) - rate) < mention.unit for rate in pool)
    if mention.kind == "year":
        return int(mention.value) in allowed.years
    if mention.kind == "receipt":
        return mention.extra[0] in allowed.receipts or mention.value in allowed.amounts
    if mention.kind == "calendar":
        low, high = _CALENDAR_RANGES[mention.extra[0]]
        return low <= mention.extra[1] <= high
    return False


def allowed_from(*sources: Any) -> Allowed:
    """Every number in tool results (nested JSON-like data) and plain texts such as the question."""
    allowed = Allowed()
    for source in sources:
        _collect(source, allowed, key=None)
    return allowed


def _collect(value: Any, allowed: Allowed, key: str | None) -> None:
    if isinstance(value, dict):
        for name, item in value.items():
            _collect(item, allowed, name)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect(item, allowed, key)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int):
        number = Decimal(value)
        allowed.amounts.add(abs(number))
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
