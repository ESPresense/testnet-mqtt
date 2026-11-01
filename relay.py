"""An MQTT broker that fills itself with a one-way copy of another broker's traffic.

Starts Mosquitto, then copies the source broker onto it. The source client only ever subscribes: this
file has no call that publishes through it. The source account should be read-only as well, so that
stays true whatever happens to this code.

The local client stands in for ESPresense nodes: a real node confirms a setting by publishing it back,
so without that echo the Companion under test would never see its own calibration land.
"""
import json
import os
import re
import signal
import ssl
import subprocess
import threading
import time

import paho.mqtt.client as mqtt
from paho.mqtt.subscribeoptions import SubscribeOptions

# Not espresense/companion/#: that is the live Companion's own state, and its leases would stop the
# build under test from ever optimizing.
DEFAULT_TOPICS = "espresense/devices/#,espresense/rooms/#,espresense/settings/#"

SET_TOPIC = "espresense/rooms/+/+/set"
SET_PATTERN = re.compile(r"^espresense/rooms/([^/]+)/([^/]+)/set$")

# Commands, not settings: a real node acts on them and doesn't publish them back.
NOT_ECHOED = {"update", "arduino_ota", "restart"}

DATA_DIR = os.environ.get("DATA_DIR", "/data")
OVERRIDES_PATH = os.path.join(DATA_DIR, "overrides.json")
WRITES_PATH = os.path.join(DATA_DIR, "writes.jsonl")
RECORD_TRAFFIC = os.environ.get("RECORD_TRAFFIC", "false").lower() == "true"

lock = threading.Lock()
overrides: dict[str, str] = {}
counts = {"copied": 0, "dropped": 0, "echoed": 0}


def load_overrides():
    if os.path.exists(OVERRIDES_PATH):
        with open(OVERRIDES_PATH) as f:
            overrides.update(json.load(f))


def save_overrides():
    with open(OVERRIDES_PATH + ".tmp", "w") as f:
        json.dump(overrides, f)
    os.replace(OVERRIDES_PATH + ".tmp", OVERRIDES_PATH)


def append_jsonl(path, entry):
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def should_copy(topic):
    """Source commands stay out, and so does a source value for a setting changed here."""
    if SET_PATTERN.match(topic):
        return False
    return topic not in overrides


def on_source_connect(client, _userdata, _flags, reason_code, _properties):
    print(f"source broker: connected ({reason_code})", flush=True)
    # Retain-as-published: otherwise the broker clears the flag on anything sent after we subscribed,
    # and an updated setting would stop being retained here.
    options = SubscribeOptions(qos=0, retainAsPublished=True)
    topics = [t.strip() for t in os.environ.get("TOPICS", DEFAULT_TOPICS).split(",") if t.strip()]
    client.subscribe([(topic, options) for topic in topics])


def on_source_message(_client, local, message):
    with lock:
        copy = should_copy(message.topic)
        counts["copied" if copy else "dropped"] += 1
    if copy:
        local.publish(message.topic, message.payload, qos=0, retain=message.retain)
    if RECORD_TRAFFIC:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        append_jsonl(os.path.join(DATA_DIR, f"traffic-{day}.jsonl"), {
            "t": time.time(),
            "topic": message.topic,
            "payload": message.payload.decode("utf-8", "replace"),
            "retain": message.retain,
        })


def on_local_connect(client, _userdata, _flags, reason_code, _properties):
    print(f"local broker: connected ({reason_code})", flush=True)
    client.subscribe(SET_TOPIC)
    # The source's copy of these is filtered out, so after a restart this is the only way they come back.
    with lock:
        for topic, payload in overrides.items():
            client.publish(topic, payload, qos=0, retain=True)


def on_local_message(client, _userdata, message):
    match = SET_PATTERN.match(message.topic)
    if not match:
        return
    node, setting = match.groups()
    payload = message.payload.decode("utf-8", "replace")
    append_jsonl(WRITES_PATH, {"t": time.time(), "node": node, "setting": setting, "value": payload})
    if setting in NOT_ECHOED:
        return

    topic = f"espresense/rooms/{node}/{setting}"
    with lock:
        overrides[topic] = payload
        save_overrides()
        counts["echoed"] += 1
    client.publish(topic, message.payload, qos=0, retain=True)


def wait_for_broker(broker):
    probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    for _ in range(50):
        if broker.poll() is not None:
            raise SystemExit("mosquitto exited during startup")
        try:
            probe.connect("127.0.0.1", 1883)
            probe.disconnect()
            return
        except OSError:
            time.sleep(0.2)
    raise SystemExit("mosquitto did not start")


def main():
    load_overrides()
    broker = subprocess.Popen(["mosquitto", "-c", "/etc/testnet-mqtt/mosquitto.conf"])
    # PID 1 ignores SIGTERM unless it handles it; pass it on so Mosquitto saves its retained messages.
    signal.signal(signal.SIGTERM, lambda *_: broker.terminate())
    wait_for_broker(broker)

    client_id = os.environ.get("CLIENT_ID", "testnet-mqtt")

    local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{client_id}-echo")
    local.on_connect = on_local_connect
    local.on_message = on_local_message
    local.connect("127.0.0.1", 1883)
    local.loop_start()

    source = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, userdata=local, protocol=mqtt.MQTTv5)
    source.on_connect = on_source_connect
    source.on_message = on_source_message
    if os.environ.get("SOURCE_USERNAME"):
        source.username_pw_set(os.environ["SOURCE_USERNAME"], os.environ.get("SOURCE_PASSWORD"))
    if os.environ.get("SOURCE_TLS", "false").lower() == "true":
        source.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    source.connect_async(os.environ["SOURCE_HOST"], int(os.environ.get("SOURCE_PORT", "1883")))
    source.loop_start()

    next_status = time.monotonic() + 60
    while broker.poll() is None:
        time.sleep(1)
        if time.monotonic() >= next_status:
            next_status += 60
            with lock:
                print(f"relay: {counts}, {len(overrides)} settings overridden", flush=True)
    raise SystemExit(f"mosquitto exited with {broker.returncode}")


if __name__ == "__main__":
    main()
