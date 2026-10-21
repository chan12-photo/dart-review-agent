"""Dev documents, AI reader: the after-fourth reports re-scored (before) vs the fixed product (after), same scorer."""
import json
import sys
from pathlib import Path

D = Path(sys.argv[1])
KEYS = ("gold_cells", "correct", "value_wrong", "label_wrong", "missing", "S1", "L1", "S2", "flagged", "product_cells",
        "not_in_gold", "unjudged_extras")
total = {"before": {}, "after": {}}
for key in ("samsung", "naver", "hanwha", "posco", "lges"):
    paths = {"before": D / "before" / f"{key}.ai.score.json", "after": D / "scores" / f"{key}.ai.score.json"}
    if not all(p.exists() for p in paths.values()):
        continue
    t = {side: json.loads(p.read_text(encoding="utf-8"))["totals"] for side, p in paths.items()}
    changed = {k: (t["before"][k], t["after"][k]) for k in KEYS if t["before"][k] != t["after"][k]}
    print(key, {k: t["after"][k] for k in KEYS}, "CHANGED " + str(changed) if changed else "same")
    for side in total:
        for k in KEYS:
            total[side][k] = total[side].get(k, 0) + t[side][k]
for side, t in total.items():
    print(side, t)
