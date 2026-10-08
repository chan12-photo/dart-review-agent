"""Which company a question, or a reader's company field, names (docs/EVAL_DESIGN.ko.md section 12.3).

Both readers use ``resolve_company``: the rules on the question, the model's
reading on its ``company`` field. The longest name found wins, so a longer
company name that contains a supported one (카카오뱅크 contains 카카오) is
that other company, not the supported one. The names come from the
active company set's vocabulary file, built from OpenDART's company list
(scripts/build_company_vocabulary.py); the active set is the development
companies unless the 3-1 evaluation switches it (dart_review/companies.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .companies import CompanySet, active_set


def normalize_company(text: str) -> str:
    """A company name as compared: legal-form words and spaces removed, Latin letters case-folded."""
    text = (text or "").replace("(주)", "").replace("㈜", "").replace("주식회사", "")
    return re.sub(r"\s+", "", text).casefold()


@dataclass(frozen=True)
class CompanyMatch:
    kind: str  # "company", "sealed", "unsupported", "group", "several", or "none"
    corp_code: str | None = None
    name: str = ""  # the longest name found, as written in the vocabulary
    candidates: tuple[str, ...] = ()  # for a group: the supported companies it may mean


_TERMS: dict[str, dict[str, tuple[str, str | None, str]]] = {}


def terms(company_set: CompanySet | None = None) -> dict[str, tuple[str, str | None, str]]:
    """normalized term -> (kind, corp code, display name) for a company set. Later entries override earlier ones."""
    company_set = company_set or active_set()
    if company_set.name not in _TERMS:
        found: dict[str, tuple[str, str | None, str]] = {}
        vocabulary = Path(__file__).with_name(company_set.vocabulary)
        for name in json.loads(vocabulary.read_text(encoding="utf-8"))["names"]:
            found[normalize_company(name)] = ("unsupported", None, name)
        for group in company_set.groups:
            found[normalize_company(group)] = ("group", None, group)
        for corp_code, name in company_set.refused.items():
            found[normalize_company(name)] = (company_set.refused_kind, corp_code, name)
        for alias, corp_code in company_set.aliases.items():
            found[normalize_company(alias)] = ("company", corp_code, company_set.companies[corp_code])
        for corp_code, name in company_set.companies.items():
            found[normalize_company(name)] = ("company", corp_code, name)
        _TERMS[company_set.name] = found
    return _TERMS[company_set.name]


# Particles that may follow a name directly ("삼전의", "엔솔은"). Codex 3-1 first review 8.
_JOINERS = ("와", "과", "랑", "하고", "및")
_PARTICLES = ("에서", "으로", "하고", "이랑", "의", "은", "는", "이", "가", "을", "를", "과", "와", "랑", "도", "에", "로", "만")


def _prepared(text: str) -> tuple[str, str, list[int]]:
    """(text as compared but with spaces kept, the same without spaces, where each kept letter came from)."""
    spaced = (text or "").replace("(주)", "").replace("㈜", "").replace("주식회사", "").casefold()
    where = [index for index, letter in enumerate(spaced) if not letter.isspace()]
    return spaced, "".join(spaced[index] for index in where), where


def _bounded(spaced: str, start: int, end: int) -> bool:
    """A supported name, alias, or group stands as a word: not part of a longer name such as 삼전순약 or 엔솔바이오."""
    before = spaced[start - 1] if start > 0 else " "
    if before.isalpha() and not spaced[:start].endswith(_JOINERS):
        return False  # a name may follow a joining particle: "카카오와셀트리온"
    rest = spaced[end:]
    if not rest or not rest[0].isalpha():
        return True  # the end, a space, punctuation, or a digit ("삼성전자2025년")
    return rest.startswith(_PARTICLES)


def resolve_company(text: str) -> CompanyMatch:
    """The company ``text`` names. Registered full names (the vocabulary) match anywhere and the longest wins;
    a supported name, an alias, or a group name must also stand as a word (``_bounded``)."""
    company_set = active_set()
    known = terms(company_set)
    spaced, compact, where = _prepared(text)
    spans = [(match.start(), match.end(), term) for term in known for match in re.finditer(re.escape(term), compact)
             if known[term][0] == "unsupported" or _bounded(spaced, where[match.start()], where[match.end() - 1] + 1)]
    outer = [span for span in spans
             if not any(other[0] <= span[0] and span[1] <= other[1] and other[1] - other[0] > span[1] - span[0]
                        for other in spans)]
    if not outer:
        return CompanyMatch("none")
    found = {}
    for start, _, term in sorted(outer):
        kind, corp_code, name = known[term]
        found.setdefault(corp_code if kind == "company" else term, (kind, corp_code, name))
    if len(found) > 1:
        return CompanyMatch("several", name=", ".join(name for _, _, name in found.values()))
    kind, corp_code, name = next(iter(found.values()))
    if kind == "group":
        return CompanyMatch("group", name=name, candidates=tuple(company_set.companies[code] for code in company_set.groups[name]))
    return CompanyMatch(kind, corp_code, name)
