#!/bin/bash
# Development measurement, devdocs_ai (not an evaluation): the five development documents read by the AI reader of
# the fixed product (180e621's product, at the main checkout), scored with the frozen D4 scorer and their development
# golds. Before: the after-fourth AI reports (product ce9c26f) re-scored with the same scorer.
# Written by Claude, 2026-10-21.
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
for v in $(env | sed -n 's/^\(OLLAMA_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
REPO="$HOME/Documents/ChatGPT/dart-review-agent"
PY="$REPO/.venv/bin/python"
OUT="$HOME/D4_dev/devdocs_ai"
STEPS="$HOME/D4_dev/devdocs_ai.steps.log"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$STEPS"; }
if [ -e "$OUT" ]; then echo "$OUT exists" >> "$STEPS"; exit 2; fi
mkdir -p "$OUT/reports" "$OUT/scores" "$OUT/before"
cd "$REPO" || exit 2
say "commit $(git rev-parse HEAD); status: $(git status --porcelain | wc -l | tr -d ' ') changed files"
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve >> "$HOME/D4_dev/devdocs_ai.ollama.log" 2>&1 &
OLLAMA_PID=$!
for i in $(seq 1 90); do ollama list > /dev/null 2>&1 && break; sleep 2; done
say "model server pid $OLLAMA_PID"
"$PY" - "$OUT" <<'PYEOF' >> "$STEPS" 2>&1
import hashlib, json, subprocess, sys, time
from pathlib import Path
out = Path(sys.argv[1]); dev = Path("eval/documents_2026-10-11_after-fourth")
pdfs = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in (Path.home() / "Desktop/감사보고서").glob("*.pdf")}
for n, key in enumerate(("samsung", "naver", "hanwha", "posco", "lges"), 1):
    gold = dev / f"d4_dev/{key}.gold.json"; mapping = dev / f"d4_dev/{key}.mapping.json"
    pdf = pdfs[json.loads(gold.read_text(encoding="utf-8"))["source"]["sha256"]]
    before = [sys.executable, "eval/d4_score.py", "--report", str(dev / f"reports/{key}.ai.report.json"), "--gold", str(gold),
              "--mapping", str(mapping), "--reader", "ai", "--out", str(out / "before" / f"{key}.ai.score.json")]
    b = subprocess.run(before, capture_output=True, text=True)
    cmd = [sys.executable, "eval/d4_score.py", "--pdf", str(pdf), "--report", str(out / "reports" / f"{key}.ai.report.json"),
           "--gold", str(gold), "--mapping", str(mapping), "--reader", "ai", "--out", str(out / "scores" / f"{key}.ai.score.json")]
    started = time.monotonic()
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(f"[{n}/5] {key}.ai: exit {r.returncode} (before rescore exit {b.returncode}), {time.monotonic() - started:.1f}s", flush=True)
    if r.returncode:
        print("   ", (r.stderr or r.stdout)[-400:].replace("\n", " | "), flush=True)
PYEOF
say "measurement done"
kill "$OLLAMA_PID" 2>/dev/null; wait "$OLLAMA_PID" 2>/dev/null
say "model server stopped; done"
