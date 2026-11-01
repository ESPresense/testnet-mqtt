#!/usr/bin/env bash
# Proves the isolation against a fake source broker, using compose.yaml as shipped plus a local build.
set -euo pipefail
cd "$(dirname "$0")/.."

export COMPOSE_PROJECT_NAME=testnet-mqtt-smoke COMPOSE_FILE=compose.yaml:compose.smoke.yaml
export SOURCE_HOST=source SOURCE_PORT=1883 UI_BIND=127.0.0.1 UI_PORT=0
export MIRROR_IMAGE=testnet-mqtt:smoke
compose() { docker compose "$@"; }

created_config=false
if [ ! -e config ]; then
  mkdir config && cp config-example/config.yaml config/ && chmod 777 config && created_config=true
fi
cleanup() {
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  if $created_config; then
    docker run --rm -v "$PWD:/w" alpine rm -rf /w/config
  fi
}
trap cleanup EXIT

fails=0
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: expected [$2], got [$3]"; fails=$((fails + 1)); fi; }
source_pub() { compose exec -T source mosquitto_pub "$@"; }
mirror_pub() { compose exec -T mirror mosquitto_pub "$@"; }
read_one() { compose exec -T "$1" mosquitto_sub -t "$2" -C 1 -W 3 2>/dev/null | tr -d '\r' || true; }
yes_no() { if "$@"; then echo true; else echo false; fi; }
contains() { printf '%s' "$1" | grep -q -- "$2"; }

docker build -q -t testnet-mqtt:smoke . >/dev/null
compose up -d --wait source mirror
sleep 2

source_pub -r -t espresense/rooms/n1/absorption -m 3.1
source_pub -r -t espresense/companion/lease/optimization -m '{"instanceId":"live"}'
source_pub -t espresense/rooms/n1/restart/set -m PRESS
compose exec -T source sh -c 'for i in 1 2 3 4 5 6; do mosquitto_pub -t espresense/devices/d1/n1 -m "{\"rssi\":-60}"; sleep 0.5; done' &
sleep 1
check "device traffic is copied" '{"rssi":-60}' "$(read_one mirror 'espresense/devices/#')"
wait
check "retained settings are copied" 3.1 "$(read_one mirror espresense/rooms/n1/absorption)"
check "source leases are not copied" "" "$(read_one mirror 'espresense/companion/#')"

mirror_pub -t espresense/rooms/n1/absorption/set -m 3.4
sleep 1
check "a write is echoed back" 3.4 "$(read_one mirror espresense/rooms/n1/absorption)"
check "a write doesn't reach the source" 3.1 "$(read_one source espresense/rooms/n1/absorption)"
check "no /set reaches the source" "" "$(read_one source 'espresense/rooms/+/+/set')"

source_pub -r -t espresense/rooms/n1/absorption -m 2.9
sleep 1
check "the source can't overwrite a written value" 3.4 "$(read_one mirror espresense/rooms/n1/absorption)"

mirror_pub -t espresense/rooms/n1/restart/set -m PRESS
sleep 1
check "commands aren't echoed" "" "$(read_one mirror espresense/rooms/n1/restart)"

compose restart mirror >/dev/null
compose up -d --wait mirror
sleep 2
check "writes survive a restart" 3.4 "$(read_one mirror espresense/rooms/n1/absorption)"

compose up -d --wait --wait-timeout 180 companion ui
sleep 5
api() { compose exec -T companion curl -s "$@"; }
check "Companion reads copied settings" true "$(yes_no contains "$(api http://localhost:8267/api/node/n1)" '"absorption":3.4')"
api -X PUT -H 'Content-Type: application/json' -d '{"calibration":{"absorption":3.7}}' http://localhost:8267/api/node/n1 >/dev/null
sleep 2
check "a Companion write comes back through the echo" true "$(yes_no contains "$(api http://localhost:8267/api/node/n1)" '"absorption":3.7')"
check "the write didn't reach the source" 2.9 "$(read_one source espresense/rooms/n1/absorption)"
check "the isolated network has no way out" true \
  "$(docker network inspect testnet-mqtt-smoke_isolated -f '{{.Internal}}')"
tcp() { compose exec -T companion sh -c "timeout 2 bash -c '</dev/tcp/$1/$2' 2>/dev/null && echo reachable || echo unreachable"; }
check "Companion can't reach the source" unreachable "$(tcp source 1883)"
check "Companion can't reach the LAN" unreachable "$(tcp 1.1.1.1 53)"
check "the UI proxy works" 200 \
  "$(curl -s -o /dev/null -w '%{http_code}' "http://$(compose port ui 8267)/healthz")"
check "the report lists the write" true "$(yes_no contains "$(scripts/report.sh)" '| n1 | absorption |')"

[ "$fails" = 0 ] && echo "All checks passed" || { echo "$fails checks failed"; exit 1; }
