#!/bin/bash
# D4 step ⑧, run 1: docs/D4_RUN_PROCEDURE.ko.md ⑧ steps 2-5 at the registered commit R, detached from the
# Claude app (nohup) so that quitting the app does not stop it. Written by Claude, 2026-10-20.
# Added before step 2: wait until the Mac is on AC power (the AI reader runs for a day or more; on battery the
# Mac would sleep or shut down in the middle). Nothing else differs from the procedure's commands.
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export GIT_TERMINAL_PROMPT=0
for v in $(env | sed -n 's/^\(OLLAMA_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done  # no other OLLAMA_ setting (contract 7)
PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
BASE="$HOME/D4_official"
STEPS="$BASE/run1.steps.log"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$STEPS"; }

say "launcher started (pid $$)"
if [ -e "$BASE/run1" ]; then say "STOP: $BASE/run1 exists"; exit 2; fi

# 0. AC power
until pmset -g batt | grep -q "AC Power"; do sleep 60; done
say "on AC power"

# 2. the model server, with the contract's command only (contract 7)
say "model server command: OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve"
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve >> "$BASE/run1.ollama.log" 2>&1 &
OLLAMA_PID=$!
say "model server pid $OLLAMA_PID"
for i in $(seq 1 90); do ollama list > /dev/null 2>&1 && break; sleep 2; done
ollama list >> "$STEPS" 2>&1

cd "$BASE/checkout" || { say "STOP: no checkout"; kill "$OLLAMA_PID"; exit 2; }
say "checkout HEAD $(git rev-parse HEAD)"

# 3. preflight, as a module from the checkout (contract 1.2); every check goes to the log
"$PY" -m eval.d4_preflight check --freeze eval/freeze_d4.json --register eval/register_d4.json \
    --registered d4-registered --remote origin --log "$BASE/run1.preflight.json" >> "$STEPS" 2>&1
say "preflight exit $?"

# 4. inputs (nothing runs)
"$PY" eval/d4_eval/run_d4.py --pdf-dir "$HOME/Desktop/D4" --scan-dir "$HOME/Desktop/D4/scans" --out "$BASE/run1" \
    --dry-run 2>&1 | tail -1 >> "$STEPS"

# 5. the run; run_d4.py itself refuses to start unless the preflight log passed at this HEAD
say "run started"
caffeinate -i "$PY" eval/d4_eval/run_d4.py --pdf-dir "$HOME/Desktop/D4" --scan-dir "$HOME/Desktop/D4/scans" \
    --out "$BASE/run1" --preflight "$BASE/run1.preflight.json" >> "$BASE/run1.console.log" 2>&1
say "run exit $?"

# 7. the model server off (only the one started here)
kill "$OLLAMA_PID" 2> /dev/null
wait "$OLLAMA_PID" 2> /dev/null
say "model server stopped; launcher done"
