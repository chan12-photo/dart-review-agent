#!/bin/bash
# Development measurement, after2 (not an evaluation): the D4 documents read by the product at the fixing commit, scored
# with the frozen D4 scorer and the registered golds. The D4 documents have been seen, so nothing here is official.
# Written by Claude, 2026-10-20. Same order as the official run: rules then ai; text, normal, tilt, blur.
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
for v in $(env | sed -n 's/^\(OLLAMA_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done
REPO="$HOME/Documents/ChatGPT/dart-review-agent"
PY="$REPO/.venv/bin/python"
OUT="$HOME/D4_dev/after2"
STEPS="$HOME/D4_dev/after2.steps.log"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$STEPS"; }
if [ -e "$OUT" ]; then echo "$OUT exists" >> "$STEPS"; exit 2; fi
mkdir -p "$OUT/reports" "$OUT/scores"
cd "$REPO" || exit 2
say "commit $(git rev-parse HEAD); status: $(git status --porcelain | wc -l | tr -d ' ') changed files"
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve >> "$HOME/D4_dev/after2.ollama.log" 2>&1 &
OLLAMA_PID=$!
for i in $(seq 1 90); do ollama list > /dev/null 2>&1 && break; sleep 2; done
say "model server pid $OLLAMA_PID"
"$PY" - "$OUT" <<'PYEOF' >> "$STEPS" 2>&1
import json, subprocess, sys, time
from pathlib import Path
out = Path(sys.argv[1]); home = Path.home()
docs = json.loads(Path("eval/d4_eval/documents.json").read_text(encoding="utf-8"))["documents"]
n = 0
for reader in ("ai",):  # after2: the AI reader only (the rules reader did not change after after1)
    for d in docs:
        for variant in ("text", "normal", "tilt", "blur"):
            n += 1
            name = f"{d['key']}.{variant}.{reader}"
            pdf = home / "Desktop/D4" / d["pdf"] if variant == "text" else home / "Desktop/D4/scans" / d["scans"][variant]["pdf"]
            cmd = [sys.executable, "eval/d4_score.py", "--pdf", str(pdf), "--report", str(out / "reports" / f"{name}.json"),
                   "--gold", d["gold"], "--mapping", d["mapping"], "--reader", reader, "--out", str(out / "scores" / f"{name}.json")]
            if variant != "text":
                cmd[-2:-2] = ["--page-map", d["scans"][variant]["map"]]
            started = time.monotonic()
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"[{n}/40] {name}: exit {result.returncode}, {time.monotonic() - started:.1f}s", flush=True)
            if result.returncode:
                print("   " + " | ".join(result.stderr.strip().splitlines()[-3:]), flush=True)
PYEOF
say "measurement done"
kill "$OLLAMA_PID" 2> /dev/null
wait "$OLLAMA_PID" 2> /dev/null
say "model server stopped; done"
