"""D4 freeze and preflight (contract 1, steps ④ and ⑧): what is fixed, and a check that the run uses exactly that.

    python eval/d4_preflight.py freeze --product P --tools T --out eval/freeze_d4.json      # step ④
    python eval/d4_preflight.py register --freeze eval/freeze_d4.json --paths <files> --out eval/register_d4.json
                                                                                           # step ⑦, then commit R
    python eval/d4_preflight.py check --freeze eval/freeze_d4.json --register eval/register_d4.json \
        --registered d4-registered --remote origin --log <run>/preflight.json             # step ⑧

Another evaluation names its profile (eval/d4_eval/document_list.py PROFILES), which fixes its records' places, its
tools, its P, and its tag; N is decided by the person at ③ and frozen at ④ (D5 contract 2, Codex D5 re-check 1-3):

    python eval/d4_preflight.py freeze --profile d5 --documents-count N --product 180e621 --tools T \
        --out eval/freeze_d5.json                    # commit it as F, tag F d5-frozen, push the tag (step ④)
    python eval/d4_preflight.py register --profile d5 --freeze eval/freeze_d5.json --paths <files> \
        --out eval/register_d5.json --remote origin
    python eval/d4_preflight.py check --profile d5 --freeze eval/freeze_d5.json --register eval/register_d5.json \
        --registered d5-registered --remote origin --log <run>.preflight.json

The freeze record names the product commit P and the tools commit T, the git object of every frozen path at
its commit (the product: dart_review/ and pyproject.toml; the tools: TOOL_PATHS), the Python version, every
installed package with its version, the model's digest, and the Ollama, Tesseract, and macOS versions.

The check runs in the checkout the run will use (a fresh ``git worktree`` at the registration commit R) and
fails unless all hold: no change in the working tree or the index and no untracked file (``git status
--porcelain``), each frozen path at HEAD is the recorded object (a commit diff alone misses uncommitted files),
dart_review is imported from this checkout, and the environment equals the record. Every check and its result
go to the log, also when one fails.

A commit cannot hold its own hash, so a file alone cannot fix R: a later commit R2 with another gold and its own
record would pass. The registration record (step ⑦) lists the git object of every registered file (the golds,
the confirmed mappings, the scan maps, the candidate record, the run commands, and the freeze record); it is
committed as R, tagged "d4-registered", and the tag is pushed before the run (contract 1.2), so R is fixed
outside the checkout. The check then requires HEAD to be the registered commit, the registered files to be the
recorded objects, P and T to be ancestors of R, and, with --remote, the pushed tag to name HEAD.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval" / "d4_eval"))
from document_list import (D4_TOOLS, PROFILES, check_document_list, frozen_count, inside,  # noqa: E402
                           profile_record)

PRODUCT_PATHS = ("dart_review", "pyproject.toml")
# the gold builder, the scorer, the candidate rules, this check, and the synthetic scan maker with its conditions
TOOL_PATHS = D4_TOOLS
MODEL = "qwen3-vl:8b"
ENVIRONMENT = ("python", "packages", "model", "ollama", "tesseract", "macos")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _object(root: Path, commit: str, path: str) -> str | None:
    try:
        return _git(root, "rev-parse", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        return None


def tag_commit(root: Path, tag: str) -> str | None:
    """The commit a local tag names, or None."""
    try:
        return _git(root, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        return None


def pushed_tag(root: Path, remote: str, tag: str) -> tuple[str | None, list[str]]:
    """The commit the tag names on ``remote`` (an annotated tag's peeled commit is the last line), and the listing."""
    try:
        listed = _git(root, "ls-remote", remote, f"refs/tags/{tag}", f"refs/tags/{tag}^{{}}")
    except subprocess.CalledProcessError as exc:
        listed = f"error: {exc.stderr.strip() if exc.stderr else exc}"
    named = [line.split()[0] for line in listed.splitlines() if line.strip() and not line.startswith("error")]
    return (named[-1] if named else None), listed.splitlines()[:2]


def regular_at_head(root: Path, path: str) -> bool:
    """``path`` is committed at HEAD as a regular file (mode 100644 or 100755, not a link), inside the repository
    without a link on the way (Codex D5 third review 2)."""
    try:
        listed = _git(root, "ls-tree", "HEAD", "--", path)
    except subprocess.CalledProcessError:
        return False
    return listed.split(" ")[0] in ("100644", "100755") and inside(root, path)


def environment() -> dict:
    """The Python, the installed packages, the model digest (``ollama list``), and Tesseract; None when unknown."""
    from importlib.metadata import distributions
    packages = sorted(f"{d.metadata['Name']}=={d.version}" for d in distributions() if d.metadata["Name"])

    def first_line(command: list[str]) -> str | None:
        try:
            out = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        lines = (out.stdout or out.stderr).strip().splitlines()
        return lines[0] if lines else None

    try:
        listed = subprocess.run(["ollama", "list"], check=True, capture_output=True, text=True, timeout=30).stdout
        model = next((line.split()[1] for line in listed.splitlines()[1:] if line.split()[:1] == [MODEL]), None)
    except (OSError, subprocess.SubprocessError, IndexError):
        model = None
    # Ollama's version can change a model's output; macOS's version is the Vision OCR's
    return {"python": platform.python_version(), "packages": packages, "model": {MODEL: model},
            "ollama": first_line(["ollama", "--version"]), "tesseract": first_line(["tesseract", "--version"]),
            "macos": platform.mac_ver()[0] or None}


def freeze_record(root: Path, product: str, tools: str, env: dict, profile: str = "d4",
                  expected_documents: int | None = None) -> dict:
    """``profile``: the evaluation (D4, the default, as it was frozen: TOOL_PATHS and no profile in the record). Any
    other profile freezes its own tools and its own P only, and records itself with N, the number of documents the
    person decided on at ③ (Codex D5 re-check 1 and 3). The check compares every path the record names."""
    product, tools = _git(root, "rev-parse", product), _git(root, "rev-parse", tools)
    extra = {}
    tool_paths = TOOL_PATHS
    if profile != "d4":
        extra = {"profile": profile_record(profile, expected_documents)}
        tool_paths = tuple(extra["profile"]["tool_paths"])
        if product != extra["profile"]["product_commit"]:
            raise ValueError(f"P {product[:7]} is not {profile}'s product commit "
                             f"{extra['profile']['product_commit'][:7]} (D5 contract 3: a closed list)")
    elif expected_documents is not None:
        raise ValueError("D4's number of documents is its list's 10: no --documents-count")
    objects = {"product": {path: _object(root, product, path) for path in PRODUCT_PATHS},
               "tools": {path: _object(root, tools, path) for path in tool_paths}}
    absent = [path for group in objects.values() for path, obj in group.items() if obj is None]
    if absent:
        raise ValueError(f"not at their commit: {', '.join(absent)}")
    return {"product_commit": product, "tools_commit": tools, "objects": objects, "environment": env,
            "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra}


def register_record(root: Path, freeze_path: str, paths: list[str], profile: str = "d4",
                    remote: str | None = None) -> dict:
    """Step ⑦: the git objects of the registered files at HEAD (committed, in a clean tree), the freeze record's
    among them. A mapping file must be confirmed: a draft mapping cannot be registered. Every file is a regular
    file inside the repository, reached without a link (Codex D5 re-check 2). A profile other than D4's registers
    its own freeze record, its document list (checked against the frozen N), its places, and every gold, mapping,
    and scan map the list names, and records its name and tag (Codex D5 re-check 3). Its freeze record must be
    the object of F, the commit its frozen tag names locally and on ``remote`` (Codex D5 third review 1)."""
    if _git(root, "status", "--porcelain", "--untracked-files=all"):
        raise ValueError("the tree is not clean: register committed files only")
    for path in [freeze_path, *paths]:
        if not inside(root, path) or not (root / path).is_file():
            raise ValueError(f"{path} is not a file inside the repository (or is reached through a link)")
    extra = {}
    if profile != "d4":
        wanted = PROFILES[profile]
        if freeze_path != wanted["freeze"]:
            raise ValueError(f"{profile} registers its freeze record {wanted['freeze']}, not {freeze_path}")
        count = frozen_count(json.loads((root / freeze_path).read_text(encoding="utf-8")), profile)
        documents = json.loads((root / wanted["documents"]).read_text(encoding="utf-8")) \
            if (root / wanted["documents"]).is_file() else {}
        check_document_list(documents, count, root=root)
        named = {wanted["documents"], wanted["places"]}
        for item in documents["documents"]:
            named |= {item["gold"], item["mapping"], *(scan["map"] for scan in item["scans"].values())}
        missing = sorted(named - set(paths))
        if missing:
            raise ValueError(f"not registered: {', '.join(missing)}")
        frozen = tag_commit(root, wanted["frozen_tag"])
        if frozen is None:
            raise ValueError(f"no tag {wanted['frozen_tag']}: F is tagged and pushed at ④")
        if remote is None or pushed_tag(root, remote, wanted["frozen_tag"])[0] != frozen:
            raise ValueError(f"the tag {wanted['frozen_tag']} on {remote} does not name {frozen[:7]}")
        # registered on a line of history that grew from F, not beside it (Codex D5 fourth review 1)
        if subprocess.run(["git", "merge-base", "--is-ancestor", frozen, "HEAD"], cwd=root,
                          capture_output=True).returncode != 0:
            raise ValueError(f"F {frozen[:7]} ({wanted['frozen_tag']}) is not an ancestor of HEAD: register after F")
        at_f, now = _object(root, frozen, freeze_path), _object(root, "HEAD", freeze_path)
        if at_f is None or at_f != now:
            raise ValueError(f"{freeze_path} at HEAD is not the record frozen at F {frozen[:7]} ({wanted['frozen_tag']})")
        extra = {"profile": profile, "tag": wanted["tag"], "frozen_commit": frozen, "freeze_object": at_f}
    objects = {}
    for path in [freeze_path, *paths]:
        obj = _object(root, "HEAD", path)
        if obj is None:
            raise ValueError(f"{path} is not committed")
        try:
            content = json.loads((root / path).read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            content = None  # not JSON: not a mapping (a mapping file that does not parse fails below)
        # a mapping by its content, not only by its name (Codex sixth review, record 1)
        if path.endswith(".mapping.json") or (isinstance(content, dict) and "decisions" in content):
            mapping = content if isinstance(content, dict) else {}
            if mapping.get("status") != "confirmed" or not mapping.get("confirmed_by") or not mapping.get("confirmed_at"):
                raise ValueError(f"{path} is not a confirmed mapping")
        objects[path] = obj
    freeze = json.loads((root / freeze_path).read_text(encoding="utf-8"))
    return {"freeze": freeze_path, "product_commit": freeze["product_commit"], "tools_commit": freeze["tools_commit"],
            "objects": objects, "based_on": _git(root, "rev-parse", "HEAD"),
            "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **extra}


TAG = PROFILES["d4"]["tag"]


def check(root: Path, record: dict, env: dict, imported_from: Path | None = None, registration: dict | None = None,
          registered: str | None = None, remote: str | None = None, profile: str = "d4") -> dict:
    """``profile``: the evaluation; its tag is looked up on ``remote`` (D4: d4-registered). A profile other than
    D4's also needs the freeze record to hold that profile, the registration to name it, its tag, and its freeze
    record, and R to be named by its tag (Codex D5 re-check 3)."""
    checks = []
    tag = PROFILES[profile]["tag"]

    def add(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    if profile != "d4":
        try:
            count, why = frozen_count(record, profile), None
        except ValueError as exc:
            count, why = None, str(exc)
        add(f"the freeze record holds the {profile} profile", count is not None, why or {"expected_documents": count})
        wanted = PROFILES[profile]
        named = (registration or {}).get("profile"), (registration or {}).get("tag"), (registration or {}).get("freeze")
        add(f"the registration is {profile}'s, with its tag and freeze record", named == (profile, tag, wanted["freeze"]),
            list(named))
        listed = set((registration or {}).get("objects") or {})
        add(f"the registration holds {profile}'s list, places, and freeze record",
            {wanted["documents"], wanted["places"], wanted["freeze"]} <= listed,
            sorted({wanted["documents"], wanted["places"], wanted["freeze"]} - listed))
        add(f"R is named by the tag {tag}", registered == tag, registered)
        frozen_tag = wanted["frozen_tag"]
        frozen = tag_commit(root, frozen_tag)
        recorded = (registration or {}).get("frozen_commit"), (registration or {}).get("freeze_object")
        at_f = _object(root, frozen, wanted["freeze"]) if frozen else None
        add(f"F ({frozen_tag}) is the registration's, its freeze record the one at HEAD",
            frozen is not None and recorded == (frozen, at_f) and at_f == _object(root, "HEAD", wanted["freeze"]),
            {"tag": frozen, "registration": list(recorded), "at_f": at_f})
        ancestor = frozen is not None and subprocess.run(["git", "merge-base", "--is-ancestor", frozen, "HEAD"],
                                                         cwd=root, capture_output=True).returncode == 0
        add(f"F ({frozen_tag}) is an ancestor of HEAD", ancestor, frozen)
        if remote is not None:
            named, listed = pushed_tag(root, remote, frozen_tag)
            add(f"the pushed tag {frozen_tag} on {remote} names F", frozen is not None and named == frozen, listed)
        for place in (wanted["freeze"], wanted["register"]):
            add(f"{place} is a regular file at HEAD, reached without a link", regular_at_head(root, place), place)
        # R is the registration commit itself: one parent, the commit registered (based_on), which grew from F, and
        # only the registration record added; a merge or a side line cannot bring F in afterwards (Codex D5 fourth
        # review 1)
        based_on = (registration or {}).get("based_on")
        try:
            parents = _git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
        except subprocess.CalledProcessError:
            parents = []
        try:
            changed = _git(root, "diff", "--name-only", based_on, "HEAD").splitlines() if based_on else None
        except subprocess.CalledProcessError:
            changed = None
        add("R's only parent is the registered commit, and R adds only the registration record",
            bool(based_on) and parents == [based_on] and changed == [wanted["register"]],
            {"based_on": based_on, "parents": parents, "changed": changed})
        grew = bool(based_on) and frozen is not None and subprocess.run(
            ["git", "merge-base", "--is-ancestor", frozen, based_on], cwd=root, capture_output=True).returncode == 0
        add(f"F ({frozen_tag}) is an ancestor of the registered commit", grew, {"F": frozen, "based_on": based_on})
        if based_on:
            differ = sorted(path for path, obj in ((registration or {}).get("objects") or {}).items()
                            if _object(root, based_on, path) != obj)
            add("the registered files at the registered commit are the recorded objects", not differ, differ)

    head = _git(root, "rev-parse", "HEAD")
    try:
        target = _git(root, "rev-parse", f"{registered}^{{commit}}") if registered else None
    except subprocess.CalledProcessError:
        target = None
    add("HEAD is the registered commit R", target is not None and head == target, {"head": head, "registered": target})
    if registration is None:
        add("registration record given", False, None)
    else:
        for path, expected in registration["objects"].items():
            found = _object(root, "HEAD", path)
            add(f"registered {path} at HEAD is the recorded object", found == expected, {"recorded": expected, "head": found})
        same = (registration.get("product_commit"), registration.get("tools_commit")) == (record["product_commit"],
                                                                                           record["tools_commit"])
        add("the registration names the frozen P and T", same, {"registration": [registration.get("product_commit"),
                                                                                   registration.get("tools_commit")]})
    for name in ("product_commit", "tools_commit"):
        ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", record[name], "HEAD"], cwd=root,
                                  capture_output=True).returncode == 0
        add(f"{name} is an ancestor of HEAD", ancestor, record[name])
    if remote is not None:
        named, listed = pushed_tag(root, remote, tag)
        add(f"the pushed tag {tag} on {remote} names HEAD", named == head, listed)

    status = _git(root, "status", "--porcelain", "--untracked-files=all")
    add("clean working tree and index (git status --porcelain)", not status, status.splitlines()[:20])
    for group in ("product", "tools"):
        for path, expected in record["objects"][group].items():
            found = _object(root, "HEAD", path)
            add(f"{group} {path} at HEAD is the frozen object", found == expected, {"frozen": expected, "head": found})
    if imported_from is not None:
        add("dart_review imported from this checkout", imported_from.resolve().is_relative_to(root.resolve()),
            str(imported_from))
    frozen = record["environment"]
    for key in ENVIRONMENT:
        same = frozen.get(key) == env.get(key) and env.get(key) is not None
        if key == "model":
            same = same and all(frozen[key].values())
        detail = ({"only_frozen": sorted(set(frozen.get(key) or []) - set(env.get(key) or [])),
                   "only_now": sorted(set(env.get(key) or []) - set(frozen.get(key) or []))}
                  if key == "packages" else {"frozen": frozen.get(key), "now": env.get(key)})
        add(f"{key} as frozen", same, detail)
    result = {"head": head, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "ok": all(c["ok"] for c in checks), "checks": checks}
    return result if profile == "d4" else {"profile": profile, **result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--product", required=True)
    freeze.add_argument("--tools", required=True)
    freeze.add_argument("--out", type=Path, required=True)
    freeze.add_argument("--documents-count", type=int, help="N, decided at ③ (not for D4)")
    reg = commands.add_parser("register")
    reg.add_argument("--freeze", required=True, help="the freeze record's path in the repository")
    reg.add_argument("--paths", nargs="+", required=True, help="the files registered (committed)")
    reg.add_argument("--out", type=Path, required=True)
    reg.add_argument("--remote", help="not for D4: the remote whose pushed frozen tag must name F")
    run = commands.add_parser("check")
    run.add_argument("--freeze", type=Path, required=True)
    run.add_argument("--register", type=Path, required=True, help="the registration record committed in R")
    run.add_argument("--registered", required=True, help=f"R: a commit, or the tag {TAG}")
    run.add_argument("--remote", required=True, help=f"the remote whose pushed tag {TAG} must name HEAD")
    run.add_argument("--log", type=Path, required=True)
    for sub in (freeze, reg, run):
        sub.add_argument("--profile", choices=sorted(PROFILES), default="d4",
                         help="the evaluation (default: d4); its paths, tools, P, and tag are fixed in document_list.py")
    args = parser.parse_args()
    if args.profile != "d4":
        # a profile's records are at its own places (Codex D5 re-check 3)
        wanted = PROFILES[args.profile]
        places = {"freeze": (args.out if args.command == "freeze" else args.freeze, wanted["freeze"])}
        if args.command == "register":
            places["register"] = (args.out, wanted["register"])
        if args.command == "check":
            places["register"] = (args.register, wanted["register"])
        for what, (given, own) in places.items():
            if Path(os.path.normpath(Path(given).absolute())) != Path(os.path.normpath((ROOT / own).absolute())):
                parser.error(f"--profile {args.profile}: the {what} record is {own}, not {given}")
            # the place itself, and every folder on the way, without a link (Codex D5 third review 2)
            if not inside(ROOT, own) or (ROOT / own).is_symlink():
                parser.error(f"--profile {args.profile}: {own} is reached through a link")
        if args.command == "register" and not args.remote:
            parser.error(f"--profile {args.profile}: --remote, where the tag {wanted['frozen_tag']} was pushed at ④")
        if args.command == "check" and args.registered != wanted["tag"]:
            parser.error(f"--profile {args.profile}: --registered is the tag {wanted['tag']}")
    if args.command == "register":
        record = register_record(ROOT, args.freeze, args.paths, args.profile, args.remote)
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"registered {len(record['objects'])} files at {record['based_on'][:7]}; commit {args.out} as R, "
              f"tag it {PROFILES[args.profile]['tag']}, and push the tag before the run")
        return 0
    if args.command == "freeze":
        record = freeze_record(ROOT, args.product, args.tools, environment(), args.profile, args.documents_count)
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        missing = [k for k, v in record["environment"].items() if v is None or v == {MODEL: None}]
        print(f"frozen P {record['product_commit'][:7]}, T {record['tools_commit'][:7]}"
              + (f"; not recorded: {', '.join(missing)}" if missing else ""))
        return 0
    import dart_review
    result = check(ROOT, json.loads(args.freeze.read_text(encoding="utf-8")), environment(), Path(dart_review.__file__),
                   json.loads(args.register.read_text(encoding="utf-8")), args.registered, args.remote, args.profile)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in result["checks"]:
        print(("ok   " if item["ok"] else "FAIL ") + item["check"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
