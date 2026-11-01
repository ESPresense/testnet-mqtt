# testnet-mqtt

An MQTT broker that fills itself with a one-way copy of another broker's traffic. Point a test build of [ESPresense-companion](https://github.com/ESPresense/ESPresense-companion) at it and the build sees your real house, but nothing it does reaches your nodes.

```
your broker ──read-only──▶ testnet-mqtt ◀──▶ Companion under test
                           (Mosquitto + relay)   (no route out)
```

## What it does

- **Copies** `espresense/devices/#`, `espresense/rooms/#` and `espresense/settings/#`. Set `TOPICS` to change that.
- **Leaves out** `espresense/companion/#`, because live leases would stop the test build optimizing, and any `/set` commands.
- **Stands in for nodes.** A real node publishes a setting back after applying it. The mirror does the same, then ignores source values for that setting so a calibration the test build chose stays in place.
- **Records** every write to `/data/writes.jsonl`. With `RECORD_TRAFFIC=true` it also saves all source traffic there, about 200 MB a day. Those files hold raw house ids.

It doesn't simulate the effect of a calibration yet. `rssi` and `distance` still come from your nodes using their real settings, so this shows what a build would decide, not how those decisions settle over time.

## Safety

The mirror only subscribes to the source broker. Give it an account that can only read `espresense/#` anyway, so that holds even if the code is wrong.

`compose.yaml` puts Companion on an `internal` Docker network with no route to your broker or LAN. That protection comes from the Compose file, not the image, so keep it if you write your own.

## Use

```bash
cp .env.example .env                 # source broker and Companion image
mkdir config && cp config-example/config.yaml config/
chmod 777 config                     # add your floors and nodes to config/config.yaml
docker compose up -d
docker compose port ui 8267          # where the UI is
scripts/report.sh                    # markdown report
docker compose down -v               # remove it and its data
```

To test a Companion PR, set `COMPANION_IMAGE` to the version its "Deploy to Docker" job printed, such as `espresense/espresense-companion:2.6.0-b17`. Don't use `beta` for this, because every PR overwrites it. To compare builds side by side, use a separate directory or `COMPOSE_PROJECT_NAME` for each.

Reports contain your node ids, so anonymise them before posting publicly.

## Run it in Crow

`.woodpecker/soak.yml` runs the same thing as a Crow pipeline, up to the 600-minute limit. It prints the report at the end of the `soak` step, and Crow cleans up the containers. The pipeline only runs on `manual` and `cron` events, so PRs never get its secrets.

Crow needs these secrets, limited to `manual` and `cron`:

| Secret | Value |
|---|---|
| `source_host`, `source_port` | The source broker |
| `house_config_b64` | `base64 -w0` of your `config.yaml`. Its mqtt section is replaced before Companion sees it |

```bash
crow pipeline create ESPresense/testnet-mqtt --branch main \
  --var COMPANION_IMAGE=espresense/espresense-companion:2.6.0-b17 --var SOAK_MINS=540
```

If your broker needs a login, add `SOURCE_USERNAME` and `SOURCE_PASSWORD` to the `mirror` step from secrets. Crow won't store an empty secret, so they aren't in the pipeline by default.

Crow's network isn't `internal`, so this has less isolation than `compose.yaml`. Companion holds no live credentials and only knows about the mirror, but it could route to your LAN. If your broker accepts anonymous writes, nothing but that default stops a bug from publishing to it. Keep the repo private in Crow, because the logs contain node ids.

## Check it

`scripts/smoke.sh` builds the image and proves the isolation against a fake source broker. CI runs it on every change.
