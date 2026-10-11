"""D4 freeze and preflight (contract 1, steps ④ and ⑧): what is fixed, and a check that the run uses exactly that.

    python eval/d4_preflight.py freeze --product P --tools T --out eval/freeze_d4.json      # step ④
    python eval/d4_preflight.py check --freeze eval/freeze_d4.json --log <run>/preflight.json  # step ⑧

The freeze record names the product commit P and the tools commit T, the git object of every frozen path at
its commit (the product: dart_review/ and pyproject.toml; the tools: TOOL_PATHS), the Python version, every
installed package with its version, the model's digest, and the Ollama, Tesseract, and macOS versions.

The check runs in the checkout the run will use (a fresh ``git worktree`` at the registration commit R) and
fails unless all hold: no change in the working tree or the index and no untracked file (``git status
--porcelain``), each frozen path at HEAD is the recorded object (a commit diff alone misses uncommitted files),
dart_review is imported from this checkout, and the environment equals the record. Every check and its result
go to the log, also when one fails.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_PATHS = ("dart_review", "pyproject.toml")
# the gold builder, the scorer, the candidate rules, this check, and the synthetic scan maker with its conditions
TOOL_PATHS = ("eval/d4_gold.py", "eval/d4_score.py", "eval/d4_candidates.py", "eval/d4_preflight.py", "eval/d4_scan.py")
MODEL = "qwen3-vl:8b"
ENVIRONMENT = ("python", "packages", "model", "ollama", "tesseract", "macos")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


def _object(root: Path, commit: str, path: str) -> str | None:
    try:
        return _git(root, "rev-parse", f"{commit}:{path}")
    except subprocess.CalledProcessError:
        return None


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


def freeze_record(root: Path, product: str, tools: str, env: dict) -> dict:
    product, tools = _git(root, "rev-parse", product), _git(root, "rev-parse", tools)
    objects = {"product": {path: _object(root, product, path) for path in PRODUCT_PATHS},
               "tools": {path: _object(root, tools, path) for path in TOOL_PATHS}}
    absent = [path for group in objects.values() for path, obj in group.items() if obj is None]
    if absent:
        raise ValueError(f"not at their commit: {', '.join(absent)}")
    return {"product_commit": product, "tools_commit": tools, "objects": objects, "environment": env,
            "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def check(root: Path, record: dict, env: dict, imported_from: Path | None = None) -> dict:
    checks = []

    def add(name: str, ok: bool, detail: object) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

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
    return {"head": _git(root, "rev-parse", "HEAD"), "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "ok": all(c["ok"] for c in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--product", required=True)
    freeze.add_argument("--tools", required=True)
    freeze.add_argument("--out", type=Path, required=True)
    run = commands.add_parser("check")
    run.add_argument("--freeze", type=Path, required=True)
    run.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "freeze":
        record = freeze_record(ROOT, args.product, args.tools, environment())
        args.out.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        missing = [k for k, v in record["environment"].items() if v is None or v == {MODEL: None}]
        print(f"frozen P {record['product_commit'][:7]}, T {record['tools_commit'][:7]}"
              + (f"; not recorded: {', '.join(missing)}" if missing else ""))
        return 0
    import dart_review
    result = check(ROOT, json.loads(args.freeze.read_text(encoding="utf-8")), environment(), Path(dart_review.__file__))
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for item in result["checks"]:
        print(("ok   " if item["ok"] else "FAIL ") + item["check"])
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
