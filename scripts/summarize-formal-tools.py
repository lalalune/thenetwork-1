from collections import Counter, defaultdict
import json
from math import ceil
from pathlib import Path
import sys

filename = Path(sys.argv[1])
rows = []
malformed = 0
for line in filename.read_text().splitlines():
    try:
        rows.append(json.loads(line))
    except json.JSONDecodeError:
        malformed += 1

starts = {(row["pid"], row["id"]): row for row in rows if row["phase"] == "start"}
ends = {(row["pid"], row["id"]): row for row in rows if row["phase"] == "end"}
by_child = {row.get("child"): row for row in starts.values() if row.get("child") is not None}

def label(row, key):
    direct = row.get(key)
    if direct is not None:
        return direct
    parent = by_child.get(row["pid"], {})
    return parent.get(key)

def summarize(scope):
    measured = sorted(row["elapsed_ms"] / 1000 for row in scope)
    return {
        "calls": len(measured),
        "sum_wall_seconds": round(sum(measured), 3),
        "median_wall_seconds": round(measured[ceil(len(measured) / 2) - 1], 3),
        "max_wall_seconds": round(measured[-1], 3),
    }

tools = defaultdict(list)
models = defaultdict(list)
for row in ends.values():
    kind = f'{row["tool"]} {row.get("mode", "...")}'
    tools[kind].append(row)
    if model := label(row, "model"):
        models[(model, kind)].append(row)

peak = Counter()
for key, row in starts.items():
    peak[row["time_ms"]] += 1
    if key in ends:
        peak[ends[key]["time_ms"]] -= 1
live, most = 0, 0
for _, change in sorted(peak.items()):
    live += change
    most = max(live, most)

print(json.dumps({
    "started": len(starts),
    "completed": len(ends),
    "ignored_partial_lines": malformed,
    "peak_observed_processes_including_nested_tools": most,
    "tools": {name: summarize(scope) for name, scope in sorted(tools.items())},
    "models": sorted(
        ({"model": model, "kind": kind, **summarize(scope)} for (model, kind), scope in models.items()),
        key=lambda row: row["sum_wall_seconds"],
        reverse=True,
    ),
    "slowest_actions": [
        dict(row, model=label(row, "model"), invariant=label(row, "invariant"))
        for row in sorted(ends.values(), key=lambda row: row["elapsed_ms"], reverse=True)[:30]
    ],
    "incomplete": [row for key, row in starts.items() if key not in ends],
}, indent=2))
