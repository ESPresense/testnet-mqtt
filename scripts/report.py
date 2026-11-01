"""Usage: report.py <run-dir>. Prints what the build under test tried to do, as markdown."""
import json
import os
import re
import sys

run = sys.argv[1]


def lines(name):
    path = os.path.join(run, name)
    return open(path, errors="replace").read().splitlines() if os.path.exists(path) else []


log = lines("companion.log")


def count(pattern):
    return sum(1 for line in log if re.search(pattern, line))


def resources():
    # Lines hold: epoch, utime and stime in clock ticks, RSS in kB.
    rows = [[float(v) for v in line.split()] for line in lines("metrics.txt") if len(line.split()) == 4]
    if len(rows) < 2:
        return "not enough samples"
    ticks_per_sec = 100
    peak_cpu = 0.0
    for a, b in zip(rows, rows[1:]):
        if b[0] > a[0]:
            peak_cpu = max(peak_cpu, ((b[1] + b[2]) - (a[1] + a[2])) / ticks_per_sec / (b[0] - a[0]))
    total = ((rows[-1][1] + rows[-1][2]) - (rows[0][1] + rows[0][2])) / ticks_per_sec / (rows[-1][0] - rows[0][0])
    return f"{total * 100:.0f}% of a core on average, {peak_cpu * 100:.0f}% peak minute, {max(r[3] for r in rows) / 1024:.0f} MB peak RSS"


print("## Test net report")
print()
print("| Measure | Value |")
print("|---|---|")
print(f"| Image | {os.environ.get('COMPANION_IMAGE', 'see the pipeline')} |")
print(f"| Proposals applied | {count('Applying ')} |")
print(f"| Proposals rejected | {count('found worse results|rejected:')} |")
print(f"| At a limit | {count('at the configured limit')} |")
print(f"| Errors in log | {count(r'\[ERR\]')} |")
print(f"| Resources | {resources()} |")
print()
print("### Writes (held here, never sent to the source broker)")
print()
writes = [json.loads(line) for line in lines("writes.jsonl")]
print(f"{len(writes)} writes")
seen = {}
for w in writes:
    key = (w["node"], w["setting"])
    first, n, _ = seen.get(key, (w["value"], 0, None))
    seen[key] = (first, n + 1, w["value"])
if seen:
    print("\n| Node | Setting | Writes | First | Latest |\n|---|---|---|---|---|")
    for (node, setting), (first, n, latest) in sorted(seen.items()):
        print(f"| {node} | {setting} | {n} | {first} | {latest} |")
