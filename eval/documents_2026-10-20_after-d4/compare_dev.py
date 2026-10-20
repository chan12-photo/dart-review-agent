"""Before (official D4 run, product 49c182b) vs after (dev run, 5cdb4e1): the same frozen scorer, no verdicts."""
import json
import sys
from pathlib import Path

H = Path.home()
BEFORE = H / "Documents/ChatGPT/dart-review-agent/eval/d4_eval/results/2026-10-20/run1"
AFTER = H / "D4_dev" / (sys.argv[2] if len(sys.argv) > 2 else "after1")
reader_filter = sys.argv[1] if len(sys.argv) > 1 else None
docs = json.loads((H / "Documents/ChatGPT/dart-review-agent/eval/d4_eval/documents.json").read_text())["documents"]


def facts(folder, name):
    p = folder / "scores" / f"{name}.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text())
    t = s["totals"]
    extras = [x for part in s["statements"] + s["product_statements_not_in_gold"] for x in part["extras"]]
    rep = json.loads((folder / "reports" / f"{name}.json").read_text())
    return {"correct": t["correct"], "gold": t["gold_cells"], "S1": t["S1"], "L1": t["L1"], "S2": t["S2"],
            "flagged": t["flagged"], "cells": t["product_cells"], "extras_unmarked": sum(not x["flagged"] for x in extras),
            "extras": extras, "statements": [(st["title"], st["page"], len(st["rows"])) for st in rep["statements"]]}


rows = []
for reader in ("rules", "ai"):
    if reader_filter and reader != reader_filter:
        continue
    for d in docs:
        for v in ("text", "normal", "tilt", "blur"):
            name = f"{d['key']}.{v}.{reader}"
            b, a = facts(BEFORE, name), facts(AFTER, name)
            if a is None:
                continue
            keys = ("correct", "S1", "L1", "S2", "flagged", "cells", "extras_unmarked")
            changed = {k: (b[k], a[k]) for k in keys if b[k] != a[k]}
            rows.append((name, b, a, changed))
            mark = "" if not changed else "  CHANGED " + ", ".join(f"{k} {x}->{y}" for k, (x, y) in changed.items())
            print(f"{name:26} correct {a['correct']:4}/{a['gold']:4} S1 {a['S1']} L1 {a['L1']} S2 {a['S2']:4} "
                  f"marked {a['flagged']:4}/{a['cells']:4} unmarked-extras {a['extras_unmarked']:3}{mark}")
            if b["statements"] != a["statements"]:
                print("     statements before:", b["statements"])
                print("     statements after: ", a["statements"])
tot = {}
for name, b, a, _ in rows:
    group = ("text" if ".text." in name else "scan") + "." + name.rsplit(".", 1)[1]
    t = tot.setdefault(group, {"before": {}, "after": {}})
    for side, f in (("before", b), ("after", a)):
        for k in ("correct", "gold", "S1", "L1", "S2", "flagged", "cells", "extras_unmarked"):
            t[side][k] = t[side].get(k, 0) + f[k]
for group, t in tot.items():
    print(group, "before", t["before"], "\n", " " * len(group), "after ", t["after"])
