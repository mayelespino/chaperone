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

---

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