"""Which company a question, or a reader's company field, names (docs/EVAL_DESIGN.ko.md section 12.3).

Both readers use ``resolve_company``: the rules on the question, the model's
reading on its ``company`` field. The longest name found wins, so a longer
company name that contains a supported one (카카오뱅크 contains 카카오) is
that other company, not the supported one. The names come from
company_vocabulary.json, built from OpenDART's company list
(scripts/build_company_vocabulary.py).
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from .companies import DEV_COMPANIES, SEALED_EVAL_COMPANIES

VOCABULARY_FILE = Path(__file__).with_name("company_vocabulary.json")
# Fixed before the runs that measure them (EVAL_DESIGN 12.3).
ALIASES = {"삼전": "00126380"}
# A group name alone may mean several companies: it is asked back, offering the supported ones.
GROUPS = {"삼성": ("00126380",)}


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


def _terms() -> dict[str, tuple[str, str | None, str]]:
    """normalized term -> (kind, corp code, display name). Later entries override earlier ones."""
    terms: dict[str, tuple[str, str | None, str]] = {}
    for name in json.loads(VOCABULARY_FILE.read_text(encoding="utf-8"))["names"]:
        terms[normalize_company(name)] = ("unsupported", None, name)
    for group in GROUPS:
        terms[normalize_company(group)] = ("group", None, group)
    for corp_code, name in SEALED_EVAL_COMPANIES.items():
        terms[normalize_company(name)] = ("sealed", corp_code, name)
    for alias, corp_code in ALIASES.items():
        terms[normalize_company(alias)] = ("company", corp_code, DEV_COMPANIES[corp_code])
    for corp_code, name in DEV_COMPANIES.items():
        terms[normalize_company(name)] = ("company", corp_code, name)
    return terms


TERMS = _terms()


def resolve_company(text: str) -> CompanyMatch:
    compact = normalize_company(text)
    spans = [(match.start(), match.end(), term) for term in TERMS for match in re.finditer(re.escape(term), compact)]
    outer = [span for span in spans
             if not any(other[0] <= span[0] and span[1] <= other[1] and other[1] - other[0] > span[1] - span[0]
                        for other in spans)]
    if not outer:
        return CompanyMatch("none")
    found = {}
    for start, _, term in sorted(outer):
        kind, corp_code, name = TERMS[term]
        found.setdefault(corp_code if kind == "company" else term, (kind, corp_code, name))
    if len(found) > 1:
        return CompanyMatch("several", name=", ".join(name for _, _, name in found.values()))
    kind, corp_code, name = next(iter(found.values()))
    if kind == "group":
        return CompanyMatch("group", name=name, candidates=tuple(DEV_COMPANIES[code] for code in GROUPS[name]))
    return CompanyMatch(kind, corp_code, name)
