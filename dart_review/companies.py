"""Development and sealed evaluation companies (see docs/SCOPE.ko.md)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

DEV_COMPANIES = {
    "00126380": "삼성전자",
    "00258801": "카카오",
    "00413046": "셀트리온",
}
# Sealed until the final evaluation is pre-registered. Development code must not fetch them.
SEALED_EVAL_COMPANIES = {
    "00266961": "NAVER",
    "00635134": "CJ제일제당",
    "00872984": "이마트",
    "01515323": "LG에너지솔루션",
}
# Official English names in OpenDART's corpCode.xml (corp_eng_name), checked against the cache by
# tests/test_company_names.py. A model may write a company in English; this maps it back (v0.1.2).
ENGLISH_NAMES = {
    "00126380": "SAMSUNG ELECTRONICS CO,.LTD",
    "00258801": "Kakao Corp.",
    "00413046": "Celltrion, Inc.",
    "00266961": "NAVER Corporation",
    "00635134": "CJ CHEILJEDANG CORP.",
    "00872984": "E-MART Inc.",
    "01515323": "LG ENERGY SOLUTION, LTD.",
}
REPORT_CODES = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
FS_DIVS = {"CFS": "연결", "OFS": "별도"}


class SealedCompanyError(Exception):
    pass


@dataclass(frozen=True)
class CompanySet:
    """The companies the product answers about (EVAL_DESIGN 12.3, docs/EVAL_CONTRACT_3-1.ko.md sections 4.4 and 7).

    ``refused`` are the companies of the other set: in development the sealed
    evaluation companies ("sealed"), in the evaluation the development ones
    ("unsupported"). Changing the active set is a configuration change, not a
    code change, in the 3-1 count of what a new company needed.
    """

    name: str
    companies: dict[str, str]  # corp code -> name
    aliases: dict[str, str]  # alias -> corp code
    groups: dict[str, tuple[str, ...]]  # a group name alone -> the supported companies it may mean
    refused: dict[str, str]
    refused_kind: str  # "sealed" or "unsupported"
    vocabulary: str  # file next to this module (scripts/build_company_vocabulary.py)


DEVELOPMENT = CompanySet("development", DEV_COMPANIES, {"삼전": "00126380"}, {"삼성": ("00126380",)},
                         SEALED_EVAL_COMPANIES, "sealed", "company_vocabulary.json")
# Fixed in docs/EVAL_CONTRACT_3-1.ko.md section 4.4 before any sealed data or question.
SEALED_3_1 = CompanySet(
    "sealed-3-1", SEALED_EVAL_COMPANIES,
    {"네이버": "00266961", "씨제이제일제당": "00635134", "CJ제일": "00635134",
     "엘지에너지솔루션": "01515323", "LG엔솔": "01515323", "엘지엔솔": "01515323", "엔솔": "01515323"},
    {"CJ": ("00635134",), "씨제이": ("00635134",), "LG": ("01515323",), "엘지": ("01515323",)},
    DEV_COMPANIES, "unsupported", "company_vocabulary_sealed-3-1.json")
COMPANY_SETS = {company_set.name: company_set for company_set in (DEVELOPMENT, SEALED_3_1)}
_active = DEVELOPMENT


def active_set() -> CompanySet:
    return _active


def supported_companies() -> dict[str, str]:
    """corp code -> name of the companies the product answers about now."""
    return _active.companies


@contextmanager
def using_company_set(name: str) -> Iterator[CompanySet]:
    """Answer about another company set inside this block (the 3-1 evaluation mode)."""
    global _active
    previous, _active = _active, COMPANY_SETS[name]
    try:
        yield _active
    finally:
        _active = previous


def ensure_not_sealed(corp_code: str) -> None:
    """Development code must not fetch a sealed company; only the evaluation set may."""
    if corp_code in SEALED_EVAL_COMPANIES and _active is not SEALED_3_1:
        raise SealedCompanyError(f"{SEALED_EVAL_COMPANIES[corp_code]} is sealed for the final evaluation")
