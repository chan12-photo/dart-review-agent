#!/bin/bash
# D5 step ⑧, run 2 (run1 was interrupted by a reboot while paused; no call of it is official): docs/D5_RUN_PROCEDURE.ko.md ⑧ steps 2-5 at the registered commit R (d5-registered), detached
# from the Claude app (nohup). Written by Claude, 2026-10-21, from D4's run2.sh with the D5 commands.
# Waits for AC power; stops before the run if the preflight does not pass (the runner refuses too).
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export GIT_TERMINAL_PROMPT=0
for v in $(env | sed -n 's/^\(OLLAMA_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$v"; done  # no other OLLAMA_ setting
PY="$HOME/Documents/ChatGPT/dart-review-agent/.venv/bin/python"
BASE="$HOME/D5_official"
STEPS="$BASE/run2.steps.log"
say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$STEPS"; }

say "launcher started (pid $$)"
if [ -e "$BASE/run2" ]; then say "STOP: $BASE/run2 exists"; exit 2; fi

until pmset -g batt | grep -q "AC Power"; do sleep 60; done
say "on AC power"

say "model server command: OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve"
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 ollama serve >> "$BASE/run2.ollama.log" 2>&1 &
OLLAMA_PID=$!
say "model server pid $OLLAMA_PID"
for i in $(seq 1 90); do ollama list > /dev/null 2>&1 && break; sleep 2; done
ollama list >> "$STEPS" 2>&1

cd "$BASE/checkout" || { say "STOP: no checkout"; kill "$OLLAMA_PID"; exit 2; }
say "checkout HEAD $(git rev-parse HEAD)"

"$PY" -m eval.d4_preflight check --profile d5 --freeze eval/freeze_d5.json --register eval/register_d5.json \
    --registered d5-registered --remote origin --log "$BASE/run2.preflight.json" >> "$STEPS" 2>&1
CHECK=$?
say "preflight exit $CHECK"
if [ "$CHECK" -ne 0 ]; then
    say "STOP: the preflight did not pass; nothing run"
    kill "$OLLAMA_PID" 2> /dev/null; wait "$OLLAMA_PID" 2> /dev/null; say "model server stopped"; exit 2
fi

"$PY" eval/d4_eval/run_d4.py --documents eval/d5_eval/documents.json --pdf-dir "$HOME/Desktop/D5" \
    --scan-dir "$HOME/Desktop/D5/scans" --out "$BASE/run2" --dry-run 2>&1 | tail -1 >> "$STEPS"

say "run started"
caffeinate -i "$PY" eval/d4_eval/run_d4.py --documents eval/d5_eval/documents.json --pdf-dir "$HOME/Desktop/D5" \
    --scan-dir "$HOME/Desktop/D5/scans" --out "$BASE/run2" --preflight "$BASE/run2.preflight.json" \
    >> "$BASE/run2.console.txt" 2>&1
say "run exit $?"

kill "$OLLAMA_PID" 2> /dev/null
wait "$OLLAMA_PID" 2> /dev/null
say "model server stopped; launcher done"
