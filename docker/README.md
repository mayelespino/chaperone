# Telegram Chaperon Bot — Docker

This is the containerized version of Chaperon. It runs all three components in a single container managed by `supervisord`:

- **`telegram-bot.py`** — the long-running Telegram bot
- **`chaperon-api.py`** — the REST API for scheduling ad-hoc checks
- **`telegram-cron.py`** — fired by `cron` inside the container on the configured schedule

This version is functionally identical to the standalone version. No code changes were needed — since all three processes share the same container, they communicate over `localhost` exactly as they do on a bare Raspberry Pi.

For full documentation on commands, configuration keys, the confirmation flow, and troubleshooting, see `standalone/README.md`. This file covers only what is different or additional in the Docker deployment.

---

## Requirements

- Docker (any recent version; tested on Docker Engine 24+)
- A `telegram-bot.ini` config file already set up (see `standalone/README.md` for how to create one)

---

## Files

| File | Purpose |
|---|---|
| `Dockerfile` | Builds the image from `python:3.11-slim`, installs dependencies, copies app files |
| `supervisord.conf` | Tells supervisord to run `telegram-bot.py`, `chaperon-api.py`, and `cron` |
| `crontab` | Cron schedule inside the container -- edit this to change the check-in time |
| `telegram-bot.py` | Identical copy of the standalone version |
| `chaperon-api.py` | Identical copy of the standalone version |
| `telegram-cron.py` | Identical copy of the standalone version |

`telegram-bot.ini` is **not** in this folder and is **not** baked into the image. It is mounted at runtime (see below), keeping your credentials out of the image entirely.

---

## Building the image

From the `chaperone/` directory:

```bash
docker build --no-cache -f docker/Dockerfile -t chaperon .
```

---

## Running the container

Mount your existing `telegram-bot.ini` from wherever it lives on the host:

```bash
docker run -d \
  --name chaperon \
  --restart unless-stopped \
  -v /home/pi/telegram-bot/telegram-bot.ini:/app/telegram-bot.ini:ro \
  -p 8001:8001 \
  chaperon
```

`-v ... :ro` mounts the config read-only so the container can read it but not modify it. `-p 8001:8001` exposes the `chaperon-api` REST API on the host so you can hit it from a browser or curl from outside the container. The Telegram bot's internal trigger listener (`127.0.0.1:8765`) is intentionally not exposed since it's only used for internal communication between processes.

---

## Viewing logs

All three processes write to stdout/stderr, which Docker captures:

```bash
docker logs chaperon -f
```

To see logs from a specific process, grep by name:

```bash
docker logs chaperon -f 2>&1 | grep telegram-bot
docker logs chaperon -f 2>&1 | grep chaperon-api
```

---

## Changing the cron schedule

Edit `crontab` before building the image. The default is Monday through Friday at 9:00 AM:

```
0 9 * * 1-5 root python3 /app/telegram-cron.py >> /proc/1/fd/1 2>&1
```

The `>> /proc/1/fd/1 2>&1` redirect sends cron output to the container's main process stdout, so it shows up in `docker logs` instead of being silently discarded. After editing, rebuild the image:

```bash
docker build -t chaperon .
docker stop chaperon && docker rm chaperon
docker run -d --name chaperon --restart unless-stopped \
  -v /home/pi/telegram-bot/telegram-bot.ini:/app/telegram-bot.ini:ro \
  -p 8001:8001 \
  chaperon
```

---

## Triggering a manual check-in

From the host:

```bash
docker exec chaperon python3 /app/telegram-cron.py
```

Or via the REST API (same as the standalone version):

```bash
curl -X POST http://localhost:8001/checks \
  -H "Content-Type: application/json" \
  -d '{"hour": 15, "minute": 30}'
```

---

## Stopping and restarting

```bash
docker stop chaperon
docker start chaperon
```

After editing `telegram-bot.ini` on the host, restart the container to pick up the new config (the file is mounted live, but the Python processes read it only at startup):

```bash
docker restart chaperon
```

---

## Timezone

The container runs in UTC by default. If `chaperon-api.py` rejects a scheduled time as "already passed" when it clearly hasn't, the container's timezone is the likely cause. Set it at runtime:

```bash
docker run -d \
  --name chaperon \
  --restart unless-stopped \
  -e TZ=America/Los_Angeles \
  -v /home/pi/telegram-bot/telegram-bot.ini:/app/telegram-bot.ini:ro \
  -p 8001:8001 \
  chaperon
```

Use any IANA timezone string (e.g. `America/New_York`, `Europe/London`, `Asia/Tokyo`). This is the Docker equivalent of the `Environment=TZ=...` line in the standalone systemd unit file.

---

## Note on the config file path

`telegram-bot.py` (and `telegram-cron.py`) read the config from `/home/pi/telegram-bot/telegram-bot.ini` by default -- a path that made sense on a Raspberry Pi but may not exist on the machine running Docker. The `docker run` command above mounts the file to `/app/telegram-bot.ini`, so you'll need to update the `config.read(...)` path near the top of `telegram-bot.py` and `telegram-cron.py` to match:

```python
config.read("/app/telegram-bot.ini")
```

This is the only code change required between the standalone and Docker versions, and it only affects the config path, not any logic.
