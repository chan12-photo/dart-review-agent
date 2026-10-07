"""The structured answer every mode produces (docs/EVAL_DESIGN.ko.md section 2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
import re
from typing import Any

from .accounts import ACCOUNTS

STATUSES = ("비교 가능", "비교 불가", "데이터 없음", "확인 필요", "나란히 표시", "되묻기")
BASIS_NAMES = ("연결", "별도")
DECISIONS = {"비교 가능": "answer", "확인 필요": "answer", "나란히 표시": "side_by_side",
             "비교 불가": "refuse", "데이터 없음": "refuse", "되묻기": "clarify"}
_RATE = re.compile(r"-?\d+\.\d{2}")

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "company": {"type": "string"},
        "account": {"type": ["string", "null"], "enum": [*ACCOUNTS, None]},
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "basis": {"type": "string", "enum": list(BASIS_NAMES)},
                    "start": {"type": ["string", "null"]},
                    "end": {"type": "string"},
                    "amount": {"type": "integer"},
                },
                "required": ["basis", "start", "end", "amount"],
                "additionalProperties": False,
            },
        },
        "change": {"type": ["integer", "null"]},
        "change_pct": {"type": ["string", "null"], "pattern": "^-?[0-9]+\\.[0-9]{2}$"},
        "answer": {"type": "string"},
        "clarifying_question": {"type": ["string", "null"]},
    },
    "required": ["status", "company", "account", "values", "change", "change_pct", "answer", "clarifying_question"],
    "additionalProperties": False,
}


class AnswerFormatError(ValueError):
    pass


@dataclass(frozen=True)
class AnswerValue:
    basis: str
    start: str | None
    end: str
    amount: int


@dataclass(frozen=True)
class Answer:
    status: str
    company: str
    account: str | None
    values: tuple[AnswerValue, ...]
    change: int | None
    change_pct: str | None
    answer: str
    clarifying_question: str | None

    @property
    def decision(self) -> str:
        return DECISIONS[self.status]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["values"] = [asdict(value) for value in self.values]
        return data


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _check_date(value: Any, field: str, nullable: bool) -> None:
    if value is None and nullable:
        return
    if not isinstance(value, str):
        raise AnswerFormatError(f"{field} must be a date string")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AnswerFormatError(f"{field} is not a YYYY-MM-DD date: {value!r}") from None


def parse_answer(content: str | dict[str, Any]) -> Answer:
    """Validate a model's answer strictly; any deviation is a format error, never repaired."""
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except ValueError:
            raise AnswerFormatError("the answer is not JSON") from None
    else:
        data = content
    if not isinstance(data, dict):
        raise AnswerFormatError("the answer is not a JSON object")
    required = ANSWER_SCHEMA["required"]
    missing = [key for key in required if key not in data]
    extra = [key for key in data if key not in required]
    if missing or extra:
        raise AnswerFormatError(f"missing fields {missing}, unexpected fields {extra}")
    # check types before membership: an unhashable value must be a format error, not a crash
    if not isinstance(data["status"], str) or data["status"] not in STATUSES:
        raise AnswerFormatError(f"unknown status {data['status']!r}")
    if not isinstance(data["company"], str):
        raise AnswerFormatError("company must be a string")
    if data["account"] is not None and (not isinstance(data["account"], str) or data["account"] not in ACCOUNTS):
        raise AnswerFormatError(f"unknown account {data['account']!r}")
    if not isinstance(data["values"], list):
        raise AnswerFormatError("values must be a list")
    values = []
    for index, item in enumerate(data["values"]):
        if not isinstance(item, dict) or sorted(item) != ["amount", "basis", "end", "start"]:
            raise AnswerFormatError(f"values[{index}] must have exactly basis, start, end, amount")
        if not isinstance(item["basis"], str) or item["basis"] not in BASIS_NAMES:
            raise AnswerFormatError(f"values[{index}].basis must be 연결 or 별도")
        _check_date(item["start"], f"values[{index}].start", nullable=True)
        _check_date(item["end"], f"values[{index}].end", nullable=False)
        if not _is_int(item["amount"]):
            raise AnswerFormatError(f"values[{index}].amount must be an integer number of won")
        values.append(AnswerValue(item["basis"], item["start"], item["end"], item["amount"]))
    if data["change"] is not None and not _is_int(data["change"]):
        raise AnswerFormatError("change must be an integer or null")
    if data["change_pct"] is not None and not (isinstance(data["change_pct"], str) and _RATE.fullmatch(data["change_pct"])):
        raise AnswerFormatError("change_pct must be a string with two decimals, or null")
    if not isinstance(data["answer"], str) or not data["answer"].strip():
        raise AnswerFormatError("answer must be a non-empty string")
    if data["clarifying_question"] is not None and not isinstance(data["clarifying_question"], str):
        raise AnswerFormatError("clarifying_question must be a string or null")
    return Answer(data["status"], data["company"], data["account"], tuple(values), data["change"],
                  data["change_pct"], data["answer"], data["clarifying_question"])
