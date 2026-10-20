"""The registered document list of an evaluation: complete and without repeats (Codex D5 review 1).

``check_document_list`` is called by the runner, the position check, and the official aggregation before they use
a list. A list must name how many documents the evaluation decided on (``expected_documents``) and hold exactly
that many, each once: a list of 9 of 10 decided companies, or one company twice, once let the aggregation give
"met" on part of the sample. D4's list (registered before this check) has no ``expected_documents``; read as D4's
own file it counts its 10 documents.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

CONDITIONS = ("normal", "tilt", "blur")
D4_DOCUMENTS = 10  # D4 contract 3.1, registered at R 1f7b6bf before expected_documents existed


def _relative(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and not PurePosixPath(path).is_absolute() and ".." not in parts


def check_document_list(documents: dict, d4_legacy: bool = False, repo_paths: bool = True) -> int:
    """The number of documents N the list must hold; ValueError unless it holds exactly N, each once.

    ``d4_legacy``: the list is D4's own registered file, whose N is D4's 10. ``repo_paths``: the golds, mappings,
    and scan maps are paths inside the repository (the runner and the position check; the aggregation reads the
    list the run read, by its SHA-256)."""
    items = documents.get("documents")
    if not isinstance(items, list) or not items:
        raise ValueError("the document list has no documents")
    expected = documents.get("expected_documents")
    if expected is None and d4_legacy:
        expected = D4_DOCUMENTS
    if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
        raise ValueError("the document list does not say how many documents were decided on (expected_documents)")
    if len(items) != expected:
        raise ValueError(f"the document list holds {len(items)} documents, not the {expected} decided on")
    for field in ("key", "rank", "corp_code", "sha256", "pdf"):
        values = [item.get(field) for item in items]
        if any(value in (None, "") for value in values):
            raise ValueError(f"a document has no {field}")
        if len(set(values)) != len(values):
            raise ValueError(f"two documents share a {field}")
    scan_hashes = []
    for item in items:
        for field in ("gold", "mapping"):
            if not isinstance(item.get(field), str) or (repo_paths and not _relative(item[field])):
                raise ValueError(f"{item['key']}: {field} is not a path inside the repository")
        scans = item.get("scans")
        if not isinstance(scans, dict) or sorted(scans) != sorted(CONDITIONS):
            raise ValueError(f"{item['key']}: the scans are not exactly {', '.join(CONDITIONS)}")
        for condition in CONDITIONS:
            scan = scans[condition]
            if not scan.get("sha256") or not scan.get("pdf") or not scan.get("map") or (repo_paths and not _relative(scan["map"])):
                raise ValueError(f"{item['key']} {condition}: a scan without its file, SHA-256, or map in the repository")
            scan_hashes.append(scan["sha256"])
    if len(set(scan_hashes)) != len(scan_hashes) or set(scan_hashes) & {item["sha256"] for item in items}:
        raise ValueError("two inputs share a SHA-256")
    return expected


def is_d4_list(path: Path, root: Path) -> bool:
    return Path(path).resolve() == (root / "eval" / "d4_eval" / "documents.json").resolve()
