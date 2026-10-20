"""The registered document list of an evaluation: complete and without repeats (Codex D5 review 1, re-check 1-2).

``check_document_list`` is called by the runner, the position check, and the official aggregation before they use
a list. The number of documents comes from **outside the list**: the evaluation profile of the freeze record
(``freeze_d5.json``, committed at ④ before any candidate PDF is opened). A list that says how many it holds
cannot be trusted with that: 1 of 10 decided companies with ``expected_documents: 1`` passed (Codex re-check 1).
D4's own list, registered before this check existed, counts its 10 documents.

Paths must be files inside the repository with no symbolic link on the way: a link inside the repository to a
file outside it passed a check of the path's spelling, and a D5 list linked to D4's took D4's exception (Codex
re-check 2).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

CONDITIONS = ("normal", "tilt", "blur")
D4_DOCUMENTS = 10  # D4 contract 3.1, registered at R 1f7b6bf before expected_documents existed
D4_LIST = Path("eval") / "d4_eval" / "documents.json"


def inside(root: Path, path: str | Path, relative_only: bool = True) -> bool:
    """``path`` (relative to ``root``, or absolute when ``relative_only`` is False) names a place under ``root``
    reached without a symbolic link."""
    given = Path(path)
    if relative_only and (given.is_absolute() or ".." in given.parts):
        return False
    full = given if given.is_absolute() else Path(root) / given
    base = Path(os.path.normpath(Path(root).absolute()))
    lexical = Path(os.path.normpath(full.absolute()))
    try:
        spelled = lexical.relative_to(base)
        real = full.resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return spelled == real  # a link on the way changes the resolved place


def is_d4_list(path: Path, root: Path) -> bool:
    """The list is D4's own registered file at its own place, not reached through a link."""
    return _same_place(path, Path(root) / D4_LIST) and inside(root, D4_LIST)


# Each evaluation's files, tag, frozen tools, and product commit (D5 contract 2-3, Codex D5 re-check 3). D4 ran
# before profiles existed: its freeze record has none, its tag and tools are d4_preflight's defaults, and its N is 10.
D4_TOOLS = ("eval/d4_gold.py", "eval/d4_score.py", "eval/d4_candidates.py", "eval/d4_preflight.py", "eval/d4_scan.py")
PROFILES = {
    "d4": {"documents": str(D4_LIST), "places": "eval/d4_eval/duplicate_places.json", "freeze": "eval/freeze_d4.json",
           "register": "eval/register_d4.json", "tag": "d4-registered", "tool_paths": list(D4_TOOLS),
           "product_commit": None},
    "d5": {"documents": "eval/d5_eval/documents.json", "places": "eval/d5_eval/duplicate_places.json",
           "freeze": "eval/freeze_d5.json", "register": "eval/register_d5.json", "tag": "d5-registered",
           "tool_paths": [*D4_TOOLS, "eval/d4_eval/run_d4.py", "eval/d4_eval/position_check.py",
                          "eval/d4_eval/official_d4.py", "eval/d4_eval/document_list.py"],
           # the closed list of D5 contract 3: 5cdb4e1 and 180e621, the later holding the earlier
           "product_commit": "180e621e21713933484fd830a33ea9a05bd271d4"},
}


def profile_record(name: str, expected_documents: int) -> dict:
    """The profile a freeze record holds: the code's profile with N, decided by the person at ③ (D5 contract 9.1)."""
    if name not in PROFILES or name == "d4":
        raise ValueError(f"no evaluation profile {name!r} to freeze (D4's freeze record has none)")
    if not isinstance(expected_documents, int) or isinstance(expected_documents, bool) or expected_documents < 1:
        raise ValueError("the number of documents decided on is a whole number of at least 1")
    return {"name": name, **PROFILES[name], "expected_documents": expected_documents}


def frozen_count(record: dict, name: str) -> int:
    """N from a freeze record whose profile is the code's profile ``name``; ValueError otherwise."""
    profile = record.get("profile") if isinstance(record, dict) else None
    if not isinstance(profile, dict):
        raise ValueError(f"the freeze record has no evaluation profile (expected {name!r})")
    try:
        same = profile == profile_record(name, profile.get("expected_documents"))
    except ValueError:
        same = False
    if not same:
        raise ValueError(f"the freeze record's profile is not {name}'s with a decided number of documents")
    return profile["expected_documents"]


def _same_place(path: Path, place: Path) -> bool:
    given = Path(path)
    full = given if given.is_absolute() else Path.cwd() / given
    return Path(os.path.normpath(full.absolute())) == Path(os.path.normpath(Path(place).absolute()))


def registered_count(path: Path, root: Path) -> tuple[str, int]:
    """The evaluation whose list ``path`` is and its N: D4's own file (10), or a profile's list at its own place in
    ``root`` with N from that profile's freeze record there, both reached without a link. Any other list is
    refused: a list that is no evaluation's has no N from outside it."""
    if is_d4_list(path, root):
        return "d4", D4_DOCUMENTS
    for name, profile in PROFILES.items():
        if name == "d4" or not _same_place(path, Path(root) / profile["documents"]):
            continue
        for place in (profile["documents"], profile["freeze"]):
            if not inside(root, place) or not (Path(root) / place).is_file():
                raise ValueError(f"{place} is not a file inside the repository (or is reached through a link)")
        record = json.loads((Path(root) / profile["freeze"]).read_text(encoding="utf-8"))
        return name, frozen_count(record, name)
    raise ValueError(f"{path} is not the document list of a registered evaluation "
                     f"({', '.join(p['documents'] for p in PROFILES.values())})")


def check_document_list(documents: dict, expected: int | None = None, d4_legacy: bool = False,
                        root: Path | None = None, relative_only: bool = True) -> int:
    """The number of documents N; ValueError unless the list holds exactly N, each once.

    ``expected``: N from outside the list (the freeze record's profile); required unless ``d4_legacy`` (the list is
    D4's own file, N = 10). The list's own ``expected_documents`` must agree with it. ``root``: when given, every
    gold, mapping, and scan map is a file under it reached without a link (``relative_only``: and spelled as a path
    relative to it, as the registration needs)."""
    items = documents.get("documents")
    if not isinstance(items, list) or not items:
        raise ValueError("the document list has no documents")
    if d4_legacy:
        if documents.get("expected_documents") not in (None, D4_DOCUMENTS):
            raise ValueError("D4's list names another number of documents than its 10")
        expected = D4_DOCUMENTS
    else:
        if not isinstance(expected, int) or isinstance(expected, bool) or expected < 1:
            raise ValueError("the decided number of documents is not given from outside the list (the freeze record's profile)")
        if documents.get("expected_documents") != expected:
            raise ValueError(f"the list says {documents.get('expected_documents')!r} documents, the profile {expected}")
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
        paths = [item.get("gold"), item.get("mapping")]
        scans = item.get("scans")
        if not isinstance(scans, dict) or sorted(scans) != sorted(CONDITIONS):
            raise ValueError(f"{item['key']}: the scans are not exactly {', '.join(CONDITIONS)}")
        for condition in CONDITIONS:
            scan = scans[condition]
            if not scan.get("sha256") or not scan.get("pdf") or not scan.get("map"):
                raise ValueError(f"{item['key']} {condition}: a scan without its file, SHA-256, or map")
            scan_hashes.append(scan["sha256"])
            paths.append(scan["map"])
        if any(not isinstance(path, str) or not path for path in paths):
            raise ValueError(f"{item['key']}: a gold, mapping, or map path is missing")
        if root is not None:
            for path in paths:
                if not inside(root, path, relative_only):
                    raise ValueError(f"{item['key']}: {path} is not a file inside the repository (or is reached through a link)")
    if len(set(scan_hashes)) != len(scan_hashes) or set(scan_hashes) & {item["sha256"] for item in items}:
        raise ValueError("two inputs share a SHA-256")
    return expected
