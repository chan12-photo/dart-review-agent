"""Development and sealed evaluation companies (see docs/SCOPE.ko.md)."""

from __future__ import annotations

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
REPORT_CODES = {"11013": "1분기보고서", "11012": "반기보고서", "11014": "3분기보고서", "11011": "사업보고서"}
FS_DIVS = {"CFS": "연결", "OFS": "별도"}


class SealedCompanyError(Exception):
    pass


def ensure_not_sealed(corp_code: str) -> None:
    if corp_code in SEALED_EVAL_COMPANIES:
        raise SealedCompanyError(f"{SEALED_EVAL_COMPANIES[corp_code]} is sealed for the final evaluation")
