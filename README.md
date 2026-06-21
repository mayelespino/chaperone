# Telegram Chaperon Bot - V1.0

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
wait_time = 120
sleep_time = 5
max_retries = 3
notify_email = you@example.com
notify_message = Chaperon has finished running. Please check the logs for details.

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
| `chaperon` | `notify_email` | Address to email when `max_retries` is reached |
| `chaperon` | `notify_message` | Body text of that email |
| `email` | `smtp_server` | SMTP host used to send the notification email |
| `email` | `smtp_port` | SMTP port (587 for STARTTLS, the common case) |
| `email` | `smtp_username` | Sending account's email address |
| `email` | `smtp_password` | Sending account's password -- for Gmail this must be an **App Password**, not the regular account password |

Every key here is read directly with no fallback -- if one is missing or misspelled, the bot will fail to start with a `KeyError`, which will show up immediately in the logs (see Troubleshooting below).

### A note on Gmail as the sender

If `smtp_username` is a Gmail address, regular password authentication won't work over SMTP. You'll need to enable 2-Step Verification on that Google account, then generate an App Password at <https://myaccount.google.com/apppasswords> and use that 16-character value as `smtp_password`. Any other SMTP provider just needs its own server/port/credentials in the same four fields.

## Running `telegram-bot.py` as a service

Running it under systemd keeps it alive across reboots and restarts it automatically if it crashes. Create

