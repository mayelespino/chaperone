# Chaperon

Chaperon is a personal safety and check-in system built around a Telegram bot. The name comes from the old-fashioned idea of a chaperon -- someone who keeps an eye on you and raises the alarm if something seems wrong.

At a scheduled time (or on demand), the bot sends a `?ok?` message to your Telegram chat. You reply with `y`, `yes`, `si`, or `1` to confirm you're fine. If you don't reply within a configurable window, the bot tries again. If you still don't reply after a configurable number of retries, it sends an email to a designated address -- a friend, a family member, a caregiver -- to let them know you haven't checked in.

Beyond the check-in flow, the bot doubles as a general-purpose communication tool: you can send your GPS location, a photo, or a voice message from Telegram and have the bot forward it by email. You can also query the host's cron schedule, schedule ad-hoc check-ins at a specific time of day via a REST API, and run quick diagnostics like `/ping` to confirm the bot is alive.

---

## Two deployment options

This repository provides the same system in two forms. The code is identical between them -- the only difference is how it is run and configured.

```
chaperon/
├── standalone/    # runs directly on a Raspberry Pi (or any Linux box) under systemd
└── docker/        # runs in a single Docker container, on any machine with Docker
```

### `standalone/`

Designed for a Raspberry Pi running Raspberry Pi OS (or any Debian-based Linux). Each component runs as a native systemd service, managed with `systemctl`. No Docker or container runtime required. This is the recommended option if you are deploying directly onto a Pi and want the simplest possible setup.

See [`standalone/README.md`](standalone/README.md) for full setup instructions.

### `docker/`

Designed to run on any machine with Docker installed -- a Pi, a cloud VM, a home server, or a laptop. All three components run inside a single container managed by `supervisord`, with `cron` running the scheduled check-in trigger inside the same container. No systemd or host-level service configuration required.

See [`docker/README.md`](docker/README.md) for full setup instructions.

---

## Components

Both versions are made of the same three scripts:

| File | What it does |
|---|---|
| `telegram-bot.py` | The long-running bot. Polls Telegram for messages, runs the confirmation flow, handles commands. |
| `chaperon-api.py` | A small FastAPI REST API for scheduling ad-hoc check-ins at a specific time of day. |
| `telegram-cron.py` | A one-shot trigger that kicks off the `?ok?` flow. Run on a schedule via cron or a systemd timer. |

---

## Configuration

Both versions share the same configuration file format. You will need to create a `telegram-bot.ini` file before running either version. See the setup instructions in the relevant `README.md` for how to create it and where to place it.

The configuration file is never baked into the Docker image -- it is always mounted from the host at runtime, keeping your credentials out of version control.

---

## Which version should I use?

Use **`standalone/`** if:
- You are deploying onto a Raspberry Pi or a Linux machine where you are comfortable with systemd
- You want the fewest moving parts and no container runtime dependency
- You are already familiar with `journalctl`, `systemctl`, and Pi OS

Use **`docker/`** if:
- You want to run Chaperon on a machine that isn't a Pi (a cloud VM, a NAS, a home server, etc.)
- You want a self-contained deployment that doesn't touch the host's systemd or cron
- You are comfortable with Docker and want to manage it alongside other containers
- You want to be able to move the deployment to a different machine without reinstalling anything

----
# Screenshots
![aperone](chapi-01.PNG)

