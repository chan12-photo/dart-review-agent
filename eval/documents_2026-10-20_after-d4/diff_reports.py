"""Report-level differences between two product reports: statements, rows, flagged values, problem sentences."""
import json
import sys
from pathlib import Path


def facts(path):
    r = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {"problems": sorted(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True)
                              for p in r.get("problems", []))}
    for st in r["statements"]:
        name = f"{st['title']}@{st['page']}"
        rows = [(row["label"], tuple((v["column"], v["value"], v["status"]) for v in row["values"])) for row in st["rows"]]
        out[name] = {"rows": rows, "problems": sorted(p if isinstance(p, str) else json.dumps(p, ensure_ascii=False, sort_keys=True)
                                                      for p in st.get("problems", []))}
    return out


a, b = facts(sys.argv[1]), facts(sys.argv[2])
if a == b:
    print("identical statements, rows, values, statuses, and problems")
for name in sorted(set(a) | set(b)):
    if a.get(name) == b.get(name):
        continue
    if name not in a or name not in b:
        print("only in", "before" if name in a else "after", name)
        continue
    if name == "problems":
        print("report problems: -", sorted(set(a[name]) - set(b[name]))[:5], "+", sorted(set(b[name]) - set(a[name]))[:5])
        continue
    ra, rb = a[name]["rows"], b[name]["rows"]
    print(name, f"rows {len(ra)} -> {len(rb)}")
    for row in [x for x in ra if x not in rb][:6]:
        print("   -", row)
    for row in [x for x in rb if x not in ra][:6]:
        print("   +", row)
    pa, pb = a[name]["problems"], b[name]["problems"]
    if pa != pb:
        print("   problems -", sorted(set(pa) - set(pb))[:4], "+", sorted(set(pb) - set(pa))[:4])
