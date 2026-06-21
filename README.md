# Telegram Chaperon Bot

A small Telegram bot, built for running on a Raspberry Pi (or any always-on Linux box), that supports two basic chat commands (`/ping`, `/echo`) plus a confirmation/check-in flow: it asks a yes/no question in the chat, waits for a reply, retries on silence, and emails you if nobody ever answers.

It's made of two scripts:

- **`telegram-bot.py`** -- the long-running service. Polls Telegram for incoming messages and runs the confirmation logic. Meant to run under systemd.
- **`telegram-cron.py`** -- a one-shot trigger. Hits a local HTTP endpoint on the running bot to kick off the confirmation flow, without talking to Telegram itself. Meant to be run from cron, a systemd timer, or by hand.

## How it works

`telegram-bot.py` runs forever, long-polling Telegram's `getUpdates` API for new messages. When it sees `/ping` or `/echo`, it responds directly. When it sees `?ok?` typed into the chat -- or when `telegram-cron.py` (or a bare `curl`) hits its local trigger endpoint -- it posts `?ok?` into the chat and waits for someone to reply with one of `y`, `yes`, `si`, or `1`.

If no recognized reply arrives within the configured wait window, the bot reports that, waits a bit, and tries again -- up to a configured maximum number of attempts. If it exhausts all retries with no confirmation, it sends a final notice in the chat and emails a configured address.

## Requirements

- Python 3.6 or later (the code uses f-strings, which won't run on Python 2 -- if you hit a `SyntaxError` pointing at an f-string, you're almost certainly invoking `python` instead of `python3`)
- The `requests` library: `pip3 install requests`
- A Telegram bot token and the numeric chat ID you want it to listen to
- (Optional, for email notifications) an SMTP account that allows sending mail -- see the Email setup section below

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

## Chat commands

Once the bot is running and you've sent it a message, it responds to:

- `/ping` -- replies with `PONG@chap`
- `/echo <text>` -- replies with your name and whatever text followed the command
- `?ok?` -- starts the confirmation flow directly from the chat, same as the cron trigger

## Troubleshooting

A few issues that come up commonly with this kind of setup:

**`SyntaxError` pointing at an f-string.** You're running it with Python 2. Use `python3` explicitly, or add a `#!/usr/bin/env python3` shebang and `chmod +x` the file.

**`KeyError` on a config value.** `configparser.read()` doesn't raise an error if the file is missing -- it just silently parses nothing. Check the path is correct and the file is readable: `config.read("path")` returns a list of files it actually parsed, which will be empty if something's wrong.

**Nothing happens when you trigger `?ok?`, with no errors anywhere.** This is the trickiest failure mode, because several different things produce identical symptoms:

- Two copies of `telegram-bot.py` running at once will silently conflict over the same long-poll connection. Check with `ps aux | grep telegram-bot.py` and make sure only one instance is alive.
- The token in your config might not match the bot you think it does. Verify with the `getMe` curl command shown above.
- If you're trying to make the bot react to a message that *it itself* sent via the API, that will never work -- Telegram's `getUpdates` only returns events happening *to* a bot (messages from users, etc.), never the bot's own outgoing messages. This is the reason this project uses the local HTTP trigger instead of having a separate script send a Telegram message for the bot to "notice."

**Editing the script doesn't seem to change its behavior.** If it's running as a systemd service, you need to restart it after every edit (`sudo systemctl restart telegram-bot.service`) -- Python doesn't reload source files on its own.

## File layout

```
telegram-bot/
├── telegram-bot.py       # the long-running service
├── telegram-bot.ini      # config (not checked in -- contains your token/credentials)
└── README.md

telegram-cron/
└── telegram-cron.py       # one-shot trigger, run from cron
```

Keep `telegram-bot.ini` out of version control -- it holds your bot token and SMTP password.
