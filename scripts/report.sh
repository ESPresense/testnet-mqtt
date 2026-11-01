#!/usr/bin/env bash
# Prints what the build under test tried to do, as markdown. Safe to run while it's going.
set -euo pipefail
cd "$(dirname "$0")/.."

compose() { docker compose "$@"; }
id=$(compose ps -q companion)
logs=$(compose logs --no-color --no-log-prefix companion)
count() { printf '%s\n' "$logs" | grep -c -E "$1" || true; }

echo "## Test net report: $(docker inspect -f '{{.Config.Image}}' "$id")"
echo
echo "| Measure | Value |"
echo "|---|---|"
echo "| Started | $(docker inspect -f '{{.State.StartedAt}}' "$id") |"
echo "| Restarts | $(docker inspect -f '{{.RestartCount}}' "$id") |"
echo "| Proposals applied | $(count 'Applying ') |"
echo "| Proposals rejected | $(count 'found worse results|rejected:') |"
echo "| At a limit | $(count 'at the configured limit') |"
echo "| Errors in log | $(count '\[ERR\]') |"
echo "| CPU / memory now | $(docker stats --no-stream --format '{{.CPUPerc}} / {{.MemUsage}}' "$id") |"
echo
echo "### Writes (held here, never sent to the source broker)"
echo
compose exec -T mirror python3 - <<'P'
import json, os
path = "/data/writes.jsonl"
rows = [json.loads(l) for l in open(path)] if os.path.exists(path) else []
print(f"{len(rows)} writes")
seen = {}
for r in rows:
    k = (r["node"], r["setting"])
    first, n, _ = seen.get(k, (r["value"], 0, None))
    seen[k] = (first, n + 1, r["value"])
if seen:
    print("\n| Node | Setting | Writes | First | Latest |\n|---|---|---|---|---|")
    for (node, setting), (first, n, latest) in sorted(seen.items()):
        print(f"| {node} | {setting} | {n} | {first} | {latest} |")
P
