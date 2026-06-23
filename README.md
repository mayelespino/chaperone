````markdown
# Telegram Chaperon Bot

## What is this?

Chaperon is a personal safety and check-in system built around a Telegram bot running on a Raspberry Pi. The name comes from the old-fashioned idea of a chaperon -- someone who keeps an eye on you and raises the alarm if something seems wrong.

The core idea is simple: at a scheduled time (or on demand), the bot sends a `?ok?` message to your Telegram chat. You reply with `y`, `yes`, `si`, or `1` to confirm you're fine. If you don't reply within a configurable window, the bot tries again. If you still don't reply after a configurable number of retries, it sends an email to a designated address -- a friend, a family member, a caregiver -- to let them know you haven't checked in.

Beyond the check-in flow, the bot doubles as a general-purpose communication tool: you can send your GPS location, a photo, or a voice message from Telegram and have the bot forward it by email. You can also query the Pi's cron schedule, schedule ad-hoc check-ins at a specific time of day via a REST API, and run quick diagnostics like `/ping` to confirm the bot is alive.

It is designed to run unattended on a Raspberry Pi with no screen attached, managed as a systemd service that restarts automatically if it crashes, and controlled entirely from your phone via Telegram.

A small Telegram bot, built for running on a Raspberry Pi (or any always-on Linux box), that supports a handful of chat commands (see Chat commands below) plus a confirmation/check-in flow: it asks a yes/no question in the chat, waits for a reply, retries on silence, and emails you if nobody ever answers.

It's made of three components:

- **`telegram-bot.py`** -- the long-running service. Polls Telegram for incoming messages and runs the confirmation logic. Meant to run under systemd.
- **`telegram-cron.py`** -- a one-shot trigger. Hits a local HTTP endpoint on the running bot to kick off the confirmation flow, without talking to Telegram itself. Meant to be run from cron, a systemd timer, or by hand.
- **`chaperon-api.py`** -- a small FastAPI service exposing a REST API for scheduling ad-hoc confirmation checks at a specific time of day, instead of relying only on a fixed cron schedule.

## How it works

`telegram-bot.py` runs forever, long-polling Telegram's `getUpdates` API for new messages. When it sees `/ping` or `/echo`, it responds directly. When it sees `?ok?` typed into the chat -- or when `telegram-cron.py`, `chaperon-api.py`, or a bare `curl` hits its local trigger endpoint -- it posts `?ok?` into the chat and waits for someone to reply with one of `y`, `yes`, `si`, or `1`.

If no recognized reply arrives within the configured wait window, the bot reports that, waits a bit, and tries again -- up to a configured maximum number of attempts. If it exhausts all retries with no confirmation, it sends a final notice in the chat and emails a configured address.

Two of the chat commands -- `@check` and `@crontab` -- depend on `chaperon-api.py` also being up and running on the same Pi, since they make local HTTP requests to it. Everything else (`/ping`, `/echo`, `?ok?`, `/help`) works with `telegram-bot.py` alone.

## Requirements

- Python 3.6 or later (the code uses f-strings, which won't run on Python 2 -- if you hit a `SyntaxError` pointing at an f-string, you're almost certainly invoking `python` instead of `python3`)
- The `requests` library: `pip3 install requests`
- `fastapi` and `uvicorn`, only needed for `chaperon-api.py`: `pip3 install fastapi uvicorn`
- A Telegram bot token and the numeric chat ID you want it to listen to
- (Optional, for email notifications) an SMTP account that allows sending mail -- see the Email setup section below

## Installation overview

The short version, end to end -- each step is covered in more detail in its own section below:

1. Install dependencies:

   ```bash
   pip3 install requests fastapi uvicorn
   ```

   (`fastapi` pulls in `pydantic` automatically -- no separate install needed. `uvicorn` and `fastapi` are only used by `chaperon-api.py`; `telegram-bot.py` and `telegram-cron.py` only need `requests`.)

2. Set up the Telegram bot via @BotFather and write `telegram-bot.ini` (see "Setting up the Telegram bot" and "Configuration file" below).
3. Copy `telegram-bot.py` to `/home/pi/telegram-bot/` and `chaperon-api.py` to `/home/pi/chaperon-api/` (or wherever you prefer -- just make sure the paths in the `.ini` file and the systemd unit files below match wherever you actually put things).
4. Install and start both systemd services:

   ```bash
   sudo cp telegram-bot.service chaperon-api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable telegram-bot.service chaperon-api.service
   sudo systemctl start telegram-bot.service chaperon-api.service
   ```

5. Confirm both are running:

   ```bash
   sudo systemctl status telegram-bot.service chaperon-api.service
   ```

6. Test from Telegram by sending `/help` to the bot -- it should list every available command. Try `/ping` next, then `@check` once `chaperon-api.py` is confirmed running, to verify the two services can actually talk to each other.

The full contents of both `.service` files, plus notes on the `-u` flag and the `TZ` environment variable, are in "Running `telegram-bot.py` as a service" and "Running `chaperon-api.py` as a service" further down.

## Setting up the Telegram bot

1. In Telegram, message [@BotFather](https://t.me/BotFather) and run `/newbot`. Follow the prompts to name it; you'll get back a token that looks like `123456789:AAExampleTokenStringHere`.
2. Send any message to your new bot from the Telegram account you want it to listen to.
3. Find your chat ID by fetching pending updates with curl, using the token from step 1:

   ```bash
   curl https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```

   The response includes a `"chat":{"id": ...}` field -- that number is your `chat_id`.
4. Sanity-check the token at any point with:

   ```bash
   curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
   ```

   A working token returns `{"ok":true,"result":{"username":"YourBotName",...}}`. A `404` usually means the token itself is wrong or wasn't substituted into the URL correctly.

## Configuration file

Both the token/chat ID and the bot's behavior are controlled by an `.ini` file that `telegram-bot.py` reads at startup. By default it expects this at `/home/pi/telegram-bot/telegram-bot.ini` -- edit the `config.read(...)` path near the top of the script if you want it elsewhere.

```ini
[telegram]
token = 123456789:AAExampleTokenStringHere
chat_id = 987654321

[chaperon]
wait_time = 60
sleep_time = 5
max_retries = 3
notify_subject = Chaperon Notification
notify_email = you@example.com
notify_message = Please check in with Mayel, he has not responded.
test_notify_subject = Test Notification
test_notify_email = you@example.com
test_notify_message = This is just a test notification from Chaperon. Please disregard.

[email]
smtp_server = smtp.gmail.com
smtp_port = 587
smtp_username = your_sending_address@gmail.com
smtp_password = your_app_password
```

| Section | Key | Meaning |
|---|---|---|
| `telegram` | `token` | Bot token from BotFather |
| `telegram` | `chat_id` | Numeric ID of the chat the bot listens to and replies in |
| `chaperon` | `wait_time` | Seconds to wait for a confirmation reply before giving up on that attempt |
| `chaperon` | `sleep_time` | Seconds to pause between retry attempts (also used as the backoff delay after a network error) |
| `chaperon` | `max_retries` | How many confirmation attempts to make before sending the final notice and email |
| `chaperon` | `notify_subject` | Email subject used by `/send` and the max-retries notification |
| `chaperon` | `notify_email` | Address to email when `/send` is used or `max_retries` is reached |
| `chaperon` | `notify_message` | Always appended to the email body when `/send` is used; also the sole body when nothing is pending |
| `chaperon` | `test_notify_subject` | Email subject used by `/send-test` |
| `chaperon` | `test_notify_email` | Address to email when `/send-test` is used |
| `chaperon` | `test_notify_message` | Appended to the email body when `/send-test` is used; also the sole body when nothing is pending |
| `email` | `smtp_server` | SMTP host used to send all outgoing email |
| `email` | `smtp_port` | SMTP port (587 for STARTTLS, the common case) |
| `email` | `smtp_username` | Sending account's email address |
| `email` | `smtp_password` | Sending account's password -- for Gmail this must be an **App Password**, not the regular account password |

Every key here is read directly with no fallback -- if one is missing or misspelled, the bot will fail to start with a `KeyError`, which will show up immediately in the logs (see Troubleshooting below).

### A note on Gmail as the sender

If `smtp_username` is a Gmail address, regular password authentication won't work over SMTP. You'll need to enable 2-Step Verification on that Google account, then generate an App Password at <https://myaccount.google.com/apppasswords> and use that 16-character value as `smtp_password`. Any other SMTP provider just needs its own server/port/credentials in the same four fields.

## Running `telegram-bot.py` as a service

Running it under systemd keeps it alive across reboots and restarts it automatically if it crashes. Create `/etc/systemd/system/telegram-bot.service`:

```ini
[Unit]
Description=Telegram Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 -u /home/pi/telegram-bot/telegram-bot.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

The `-u` flag matters -- without it, Python buffers stdout when it isn't connected to a terminal, which means anything the script prints won't show up in the logs until the buffer flushes, making it look like nothing is happening even when it is.

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service
```

Watch it run with:

```bash
sudo journalctl -u telegram-bot.service -f
```

## Using `telegram-cron.py`

This script needs no config file and no Telegram credentials -- it just makes a local HTTP request to the already-running bot:

```bash
python3 telegram-cron.py
```

or, equivalently, skip the script entirely and run:

```bash
curl http://127.0.0.1:8765/ok-trigger
```

Either one starts the same confirmation flow as if you'd typed `?ok?` into the chat yourself. This is meant to be scheduled -- via `crontab -e` or a systemd timer -- to trigger periodic check-ins automatically.

Note that the endpoint is bound to `127.0.0.1` only, so it can't be triggered from outside the Pi itself; that's intentional.

## Using `chaperon-api.py`

While `telegram-cron.py` is good for a fixed, recurring schedule, `chaperon-api.py` lets you schedule a one-off confirmation check for a specific time today, on demand, via a REST API. It doesn't talk to Telegram directly either -- like `telegram-cron.py`, it just hits `telegram-bot.py`'s local `127.0.0.1:8765/ok-trigger` endpoint once the scheduled time arrives.

Run it directly with:

```bash
python3 chaperon-api.py
```

It listens on port `8001` by default. Schedule a check with a `POST` request specifying `hour` (0-23) and `minute` (0-59):

```bash
curl -X POST http://localhost:8001/checks -H "Content-Type: application/json" -d '{"hour": 15, "minute": 30}'
```

A successful response looks like:

```json
{"id": "b7f56fa6-d128-445d-8661-60947e2554d9", "scheduled_for": "2026-06-21T15:30:00", "seconds_from_now": 932}
```

If the requested time has already passed today, you'll get a `400` instead, with the server's current time included so you can tell at a glance whether the request was just made too late or whether something's actually wrong with the server's clock:

```json
{"detail": "15:30 has already passed today (current server time is 15:31:02)."}
```

Interactive API docs are available for free at `http://<pi-ip>:8001/docs` once it's running, useful for testing without curl.

There's also a `GET /crontab` endpoint that returns the crontab of whatever user the service runs as (per the systemd unit below, that's `pi`):

```bash
curl http://localhost:8001/crontab
```

```json
{"crontab": "*/5 * * * * /home/pi/telegram-cron/telegram-cron.py\n"}
```

If no crontab has been set up for that user yet, you'll get an empty `crontab` field with an explanatory `message` instead. Note this endpoint has no authentication -- since the API binds to `0.0.0.0`, anything that can reach port `8001` on your network can read the crontab contents. That's read-only and low-risk on a home LAN, but worth knowing if this box is ever exposed beyond it.

### Running `chaperon-api.py` as a service

Same idea as `telegram-bot.service`. Create `/etc/systemd/system/chaperon-api.service`:

```ini
[Unit]
Description=Chaperon API
After=network.target

[Service]
Environment=TZ=America/Los_Angeles
WorkingDirectory=/home/pi/chaperon-api
ExecStart=/usr/bin/python3 -u /home/pi/chaperon-api/chaperon-api.py
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

The explicit `Environment=TZ=...` matters here: `chaperon-api.py` computes "is this time today still in the future" using the process's local time, and if the environment that starts it doesn't carry the timezone you expect, that comparison will silently use the wrong reference point -- set it to whichever IANA timezone (e.g. `America/Los_Angeles`, `America/New_York`) matches where the Pi actually is.

Enable and start it the same way:

```bash
sudo systemctl daemon-reload
sudo systemctl enable chaperon-api.service
sudo systemctl start chaperon-api.service
sudo journalctl -u chaperon-api.service -f
```

## Chat commands

All commands live in a single `COMMANDS` dictionary in `telegram-bot.py` mapping each command string to a function -- adding a new one means writing a function and adding one line to that dictionary, nothing else needs to change. Once the bot is running and you've sent it a message, it responds to:

| Command | Parameters | What it does | Example |
|---|---|---|---|
| `/ping` | none | Replies with `PONG@chap` -- useful as a quick liveness check. | `/ping` |
| `/echo <text>` | the text to echo | Replies with your name plus whatever text followed the command. | `/echo hello there` |
| `?ok?` | none | Starts the confirmation flow directly in this chat -- same as the local HTTP trigger, but initiated by typing it yourself. Waits for a reply of `y`, `yes`, `si`, or `1`. | `?ok?` |
| `@check HH:MM` | an hour:minute, 24-hour format | Asks `chaperon-api.py` to schedule a one-time `?ok?` check at that time today. Requires `chaperon-api.py` to be running. | `@check 15:30` |
| `@crontab` | none | Asks `chaperon-api.py` for the crontab contents and posts them back into the chat. Requires `chaperon-api.py` to be running. | `@crontab` |
| `/location` | none | Tells you how to share your location via Telegram's attachment menu. Once you share it, the bot replies with coordinates and a Google Maps link. | `/location` |
| `/send [message]` | optional extra text | Emails any pending media (location, photo, voice) with `notify_message` appended. If an optional message is provided it is appended after `notify_message`. If nothing is pending, emails the optional message or `notify_message` on its own. | `/send` or `/send please call me` |
| `/send-test [message]` | optional extra text | Same as `/send` but uses `test_notify_email`, `test_notify_subject`, and `test_notify_message` from the config. Useful for verifying email delivery without touching the real notification address. | `/send-test` or `/send-test this is a test` |
| `/help` | none | Shows a help screen listing all of the above. | `/help` |

If `@check` or `@crontab` come back with `"Could not reach chaperon-api: ..."`, that means `chaperon-api.py` isn't running or isn't reachable on `localhost:8001` -- check `sudo systemctl status chaperon-api.service`.

### `/send` examples

**Sending your location by email:**
1. Type `/location` -- the bot tells you to use Telegram's attachment icon.
2. Tap the 📎 attachment icon in the message box and choose **Location**.
3. The bot replies with the coordinates and a Google Maps link, and prompts you to type `/send`.
4. Type `/send` -- the email body contains the Maps link followed by `notify_message` from the config.
5. Optionally: `/send I am at the park` -- appends "I am at the park" after `notify_message` in the email body.

**Sending a photo by email:**
1. Tap the 📎 attachment icon and choose **Photo**, then send a photo from your camera roll.
2. The bot replies: `Photo received. Type /send to email it as an attachment.`
3. Type `/send` -- the photo is attached as a JPEG; the email body reads "Attached photo from Telegram." followed by `notify_message`.
4. Optionally: `/send here is the damage` -- appends "here is the damage" after `notify_message`.

**Sending a voice message by email:**
1. Hold the microphone icon in Telegram and record a voice message, then send it.
2. The bot replies: `Voice message received. Type /send to email it as an attachment.`
3. Type `/send` -- the voice file is attached as OGG audio; the email body reads "Attached voice from Telegram." followed by `notify_message`.
4. Optionally: `/send listen to this` -- appends "listen to this" after `notify_message`.

**Using `/send-test` to verify email delivery:**
1. Type `/send-test` with no media pending -- sends an email to `test_notify_email` with `test_notify_message` as the body.
2. Type `/send-test this is a custom message` -- same but appends "this is a custom message" to the body.
3. Useful for confirming SMTP credentials and delivery before relying on `/send` for real notifications.

Note: Telegram's Bot API caps file downloads at 20 MB -- a very long voice message or an unusually large photo will fail at the download step with an error message in the chat. For normal voice memos and phone photos this limit is rarely hit in practice.

## Troubleshooting

A few issues that come up commonly with this kind of setup:

**`SyntaxError` pointing at an f-string.** You're running it with Python 2. Use `python3` explicitly, or add a `#!/usr/bin/env python3` shebang and `chmod +x` the file.

**`KeyError` on a config value.** `configparser.read()` doesn't raise an error if the file is missing -- it just silently parses nothing. Check the path is correct and the file is readable: `config.read("path")` returns a list of files it actually parsed, which will be empty if something's wrong.

**Nothing happens when you trigger `?ok?`, with no errors anywhere.** This is the trickiest failure mode, because several different things produce identical symptoms:

- Two copies of `telegram-bot.py` running at once will silently conflict over the same long-poll connection. Check with `ps aux | grep telegram-bot.py` and make sure only one instance is alive.
- The token in your config might not match the bot you think it does. Verify with the `getMe` curl command shown above.
- If you're trying to make the bot react to a message that *it itself* sent via the API, that will never work -- Telegram's `getUpdates` only returns events happening *to* a bot (messages from users, etc.), never the bot's own outgoing messages. This is the reason this project uses the local HTTP trigger instead of having a separate script send a Telegram message for the bot to "notice."

**Editing the script doesn't seem to change its behavior.** If it's running as a systemd service, you need to restart it after every edit (`sudo systemctl restart telegram-bot.service`) -- Python doesn't reload source files on its own.

**`chaperon-api.py` rejects a time as "already passed" when it clearly hasn't.** This usually isn't a logic bug -- it's that the process computing `datetime.now()` doesn't have the timezone you think it does. This can happen if the process was started from a different terminal session, login shell, or service environment than the one you're checking the time from. Compare `python3 -c "from datetime import datetime; print(datetime.now())"` run in the same environment that started the process against `date`; if they disagree, restart the process from an environment with the correct `TZ`, or set it explicitly (see the systemd section above).

**`@check` or `@crontab` reply with "Could not reach chaperon-api".** These two commands work by making an HTTP request from `telegram-bot.py` to `chaperon-api.py` on `localhost:8001` -- if that service isn't running, isn't listening on that port, or crashed, this is exactly what you'll see. Check `sudo systemctl status chaperon-api.service` and `sudo journalctl -u chaperon-api.service -f`.

## File layout

```
telegram-bot/
├── telegram-bot.py       # the long-running service
├── telegram-bot.ini      # config (not checked in -- contains your token/credentials)
└── README.md

telegram-cron/
└── telegram-cron.py       # one-shot trigger, run from cron

chaperon-api/
└── chaperon-api.py        # REST API for scheduling ad-hoc checks and reading the crontab
```

`telegram-bot.service` and `chaperon-api.service` aren't part of either project directory -- they get copied into `/etc/systemd/system/` directly, per the installation steps above.

Keep `telegram-bot.ini` out of version control -- it holds your bot token and SMTP password.
````