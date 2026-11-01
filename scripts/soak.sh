#!/bin/sh
# Usage: soak.sh <run-dir>
# Fails the run if Companion stops answering, otherwise waits out SOAK_MINS and prints the report.
set -eu

run=$1
ready=0
for _ in $(seq 1 30); do
  if wget -q -O /dev/null http://companion:8267/healthz; then ready=1; break; fi
  sleep 10
done
[ "$ready" = 1 ] || { echo "Companion never came up"; exit 1; }

misses=0
for minute in $(seq 1 "$SOAK_MINS"); do
  sleep 60
  if wget -q -O /dev/null http://companion:8267/healthz; then misses=0; else misses=$((misses + 1)); fi
  [ "$misses" -lt 5 ] || { echo "Companion stopped answering at minute $minute"; python3 scripts/report.py "$run"; exit 1; }
done

python3 scripts/report.py "$run"
