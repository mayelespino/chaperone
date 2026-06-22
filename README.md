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
| `/send` | none | Emails the most recently shared voice message or photo as an attachment, or the bot's last text reply if no media is pending. Clears the pending attachment after sending. | See examples below |
| `/help` | none | Shows a help screen listing all of the above. | `/help` |

If `@check` or `@crontab` come back with `"Could not reach chaperon-api: ..."`, that means `chaperon-api.py` isn't running or isn't reachable on `localhost:8001` -- check `sudo systemctl status chaperon-api.service`.

### `/send` examples

**Sending your location by email:**
1. Type `/location` -- the bot tells you to use Telegram's attachment icon.
2. Tap the 📎 attachment icon in the message box and choose **Location**.
3. The bot replies: `Location received: 37.386, -122.083 -- https://maps.google.com/?q=37.386,-122.083`
4. Type `/send` -- the bot emails that Maps link to `notify_email` and replies `Sent to email.`

**Sending a photo by email:**
1. Tap the 📎 attachment icon and choose **Photo**, then send a photo from your camera roll.
2. The bot replies: `Photo received. Type /send to email it as an attachment.`
3. Type `/send` -- the bot downloads the photo from Telegram, attaches it to an email as a JPEG, sends it to `notify_email`, and replies `Sent to email as an attachment.`

**Sending a voice message by email:**
1. Hold the microphone icon in Telegram and record a voice message, then send it.
2. The bot replies: `Voice message received. Type /send to email it as an attachment.`
3. Type `/send` -- the bot downloads the voice file from Telegram, attaches it to an email as an OGG audio file, sends it to `notify_email`, and replies `Sent to email as an attachment.`

Note: Telegram's Bot API caps file downloads at 20 MB regardless of what you send -- a very long voice message or an unusually large photo will fail at the download step with an error message in the chat. For normal voice memos and phone photos this limit is rarely hit in practice.