#!/usr/bin/env python3
"""
telegram-bot.py

Long-running Telegram bot. Polls Telegram via getUpdates() for commands
typed directly into the chat (/ping, /echo, ?ok?), and also runs a small
local-only HTTP listener (127.0.0.1:8765) so that telegram-cron.py (or a
plain curl command) can trigger the ?ok? confirmation flow without going
through Telegram at all.
"""
import requests, time, threading, configparser, smtplib
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer

config = configparser.ConfigParser()
config.read("/home/pi/telegram-bot/telegram-bot.ini")

TOKEN = config["telegram"]["token"]
CHAT_ID = int(config["telegram"]["chat_id"])
CONFIRMATION_WAIT_SECONDS = int(config["chaperon"]["wait_time"])
RETRY_SLEEP_SECONDS = int(config["chaperon"]["sleep_time"])
MAX_RETRIES = int(config["chaperon"]["max_retries"])
NOTIFY_EMAIL = config["chaperon"]["notify_email"]
NOTIFY_MESSAGE = config["chaperon"]["notify_message"]
SMTP_SERVER = config["email"]["smtp_server"]
SMTP_PORT = int(config["email"]["smtp_port"])
SMTP_USERNAME = config["email"]["smtp_username"]
SMTP_PASSWORD = config["email"]["smtp_password"]
offset = 0
no_confirmation_count = 0
last_bot_message = ""
last_media = None

VALID_CONFIRMATIONS = {"y", "yes", "si", "1"}

# Shared connection pool -- avoids a fresh TCP/TLS handshake on every
# single call to the Telegram API, which was adding noticeable latency
# to each poll and to send().
session = requests.Session()

# Long-poll window for getUpdates(). Lower = faster reaction to the
# local HTTP trigger (worst case wait before the main loop notices
# trigger_event is roughly POLL_TIMEOUT seconds), at the cost of more
# frequent empty round trips to Telegram while idle.
POLL_TIMEOUT = 10

# chaperon-api.py's scheduling endpoint -- used by the @check command
# to schedule a future ?ok? trigger instead of running one right now.
CHAPERON_API_URL = "http://localhost:8001/checks"

# chaperon-api.py's crontab endpoint -- used by the @crontab command.
CHAPERON_API_CRONTAB_URL = "http://localhost:8001/crontab"


def ping(parameters, update):
    send("PONG@chap")


def echo(parameters, update):
    first_name = update.get("message", {}).get("from", {}).get("first_name", "")
    last_name = update.get("message", {}).get("from", {}).get("last_name", "")
    send(f"{first_name} {last_name}: {' '.join(parameters)}")


######################################################################
# Telegram helpers
######################################################################


def send(text):
    global last_bot_message
    last_bot_message = text
    try:
        session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        print(f"send() failed: {e}")


def send_email(subject, body, attachment=None):
    """attachment, if given: {"filename": ..., "mime_type": "type/subtype", "data": bytes}"""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_USERNAME
    msg["To"] = NOTIFY_EMAIL
    msg.set_content(body)

    if attachment:
        maintype, subtype = attachment["mime_type"].split("/", 1)
        msg.add_attachment(
            attachment["data"],
            maintype=maintype,
            subtype=subtype,
            filename=attachment["filename"],
        )

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        return True, None
    except Exception as e:
        return False, str(e)


def download_telegram_file(file_id):
    """Fetches a file's bytes from Telegram given its file_id. Returns (bytes, None) or (None, error)."""
    try:
        r = session.get(
            f"https://api.telegram.org/bot{TOKEN}/getFile",
            params={"file_id": file_id},
            timeout=10,
        )
        data = r.json()
        if not data.get("ok", False):
            return None, str(data)
        file_path = data["result"]["file_path"]

        file_r = session.get(
            f"https://api.telegram.org/file/bot{TOKEN}/{file_path}",
            timeout=20,
        )
        if not file_r.ok:
            return None, f"Download failed: {file_r.status_code}"
        return file_r.content, None
    except requests.exceptions.RequestException as e:
        return None, str(e)


def send_notification_email():
    ok, error = send_email("Chaperon Notification", NOTIFY_MESSAGE)
    if not ok:
        print(f"send_notification_email() failed: {error}")


def schedule_check_via_api(hour, minute):
    """Asks chaperon-api.py to schedule a future ?ok? trigger. Returns (ok, message)."""
    try:
        r = session.post(CHAPERON_API_URL, json={"hour": hour, "minute": minute}, timeout=10)
    except requests.exceptions.RequestException as e:
        return False, f"Could not reach chaperon-api: {e}"

    try:
        data = r.json()
    except ValueError:
        return False, f"Unexpected response from chaperon-api: {r.text}"

    if not r.ok:
        return False, str(data.get("detail", data))

    return True, f"Check scheduled for {data.get('scheduled_for')}."


def fetch_crontab_via_api():
    """Asks chaperon-api.py for the crontab contents. Returns text to send back."""
    try:
        r = session.get(CHAPERON_API_CRONTAB_URL, timeout=10)
    except requests.exceptions.RequestException as e:
        return f"Could not reach chaperon-api: {e}"

    try:
        data = r.json()
    except ValueError:
        return f"Unexpected response from chaperon-api: {r.text}"

    if not r.ok:
        return str(data.get("detail", data))

    content = data.get("crontab", "")
    if not content.strip():
        return data.get("message", "Crontab is empty.")
    return content


def get_updates():
    global offset
    try:
        r = session.get(
            f"https://api.telegram.org/bot{TOKEN}/getUpdates",
            params={"offset": offset, "timeout": POLL_TIMEOUT},
            timeout=POLL_TIMEOUT + 5,
        )
        data = r.json()
        if not data.get("ok", False):
            print(f"Telegram API error: {data}")
            return []
        return data.get("result", [])
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        print(f"Connection error, will retry: {e}")
        time.sleep(RETRY_SLEEP_SECONDS)
        return []


def wait_for_confirmation(timeout_seconds=CONFIRMATION_WAIT_SECONDS):
    """Block, polling Telegram, until a recognized confirmation arrives or the timeout elapses."""
    global offset
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for update in get_updates():
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            if msg.get("chat", {}).get("id") != CHAT_ID:
                continue
            answer = msg.get("text", "").strip().lower()
            if answer in VALID_CONFIRMATIONS:
                return True
    return False


def confirm_and_report():
    global no_confirmation_count
    try:
        while True:
            confirmed = wait_for_confirmation()

            if confirmed:
                no_confirmation_count = 0
                send("Confirmed.")
                break

            no_confirmation_count += 1

            if no_confirmation_count >= MAX_RETRIES:
                send("Max number of retries reached. The bot will now notify.")
                send_notification_email()
                no_confirmation_count = 0
                break

            remaining = MAX_RETRIES - no_confirmation_count
            send(f"No confirmation received. I will retry {remaining} more time(s).")
            time.sleep(RETRY_SLEEP_SECONDS)
    except Exception as e:
        send(f"Error: {e}")


def confirm(parameters, update):
    confirm_and_report()


def check(parameters, update):
    if not parameters:
        send("Usage: @check HH:MM")
        return
    try:
        hour_str, minute_str = parameters[0].split(":")
        hour, minute = int(hour_str), int(minute_str)
    except ValueError:
        send("Invalid time format. Use @check HH:MM (e.g. @check 15:30).")
        return
    _, message = schedule_check_via_api(hour, minute)
    send(message)


def crontab(parameters, update):
    send(fetch_crontab_via_api())


def location(parameters, update):
    send(
        "Please tap the attachment icon (\U0001F4CE) in the message box and "
        "choose 'Location' to share your location."
    )


def send_command(parameters, update):
    global last_media
    if last_media:
        file_bytes, error = download_telegram_file(last_media["file_id"])
        if file_bytes is None:
            send(f"Failed to download attachment: {error}")
            return
        extension = last_media["mime_type"].split("/")[-1]
        filename = f"{last_media['type']}.{extension}"
        ok, error = send_email(
            "Chaperon Attachment",
            f"Attached {last_media['type']} from Telegram.",
            attachment={"filename": filename, "mime_type": last_media["mime_type"], "data": file_bytes},
        )
        last_media = None
        send("Sent to email as an attachment." if ok else f"Failed to send email: {error}")
        return

    if not last_bot_message:
        send("Nothing to send yet.")
        return
    ok, error = send_email("Chaperon Message", last_bot_message)
    send("Sent to email." if ok else f"Failed to send email: {error}")


HELP_TEXT = (
    "Available commands:\n"
    "\n"
    "/ping\n"
    "  No parameters.\n"
    "  Replies with PONG@chap.\n"
    "  Example: /ping\n"
    "\n"
    "/echo <text>\n"
    "  Replies with your name and whatever text follows the command.\n"
    "  Example: /echo hello there\n"
    "\n"
    "?ok?\n"
    "  Starts the confirmation flow directly in this chat -- asks for a\n"
    "  yes/no reply and waits for one of: y, yes, si, 1\n"
    "  Example: ?ok?\n"
    "\n"
    "@check HH:MM\n"
    "  Schedules a one-time confirmation check for that time today,\n"
    "  via chaperon-api.\n"
    "  Example: @check 15:30\n"
    "\n"
    "@crontab\n"
    "  No parameters.\n"
    "  Shows the contents of this Pi's crontab, via chaperon-api.\n"
    "  Example: @crontab\n"
    "\n"
    "/location\n"
    "  No parameters.\n"
    "  Tells you how to share your location via Telegram's attachment menu.\n"
    "  Example: /location\n"
    "\n"
    "/send\n"
    "  No parameters.\n"
    "  Emails the most recently shared voice message or photo as an\n"
    "  attachment, or falls back to emailing the bot's last text reply\n"
    "  if nothing's pending.\n"
    "  Example: record a voice message, then /send\n"
    "\n"
    "/help\n"
    "  No parameters.\n"
    "  Shows this help screen.\n"
    "  Example: /help"
)


def help_command(parameters, update):
    send(HELP_TEXT)


COMMANDS = {
    "/ping": ping,
    "/echo": echo,
    "?ok?": confirm,
    "@check": check,
    "@crontab": crontab,
    "/location": location,
    "/send": send_command,
    "/help": help_command,
}


######################################################################
# Local HTTP trigger -- 127.0.0.1 only, lets telegram-cron.py (or curl)
# kick off the ?ok? flow without sending a Telegram message at all.
######################################################################
trigger_event = threading.Event()


class TriggerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok-trigger":
            trigger_event.set()
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silence default request logging


def start_trigger_server():
    HTTPServer(("127.0.0.1", 8765), TriggerHandler).serve_forever()


threading.Thread(target=start_trigger_server, daemon=True).start()

######################################################################
# Main loop
######################################################################
while True:
    if trigger_event.is_set():
        trigger_event.clear()
        send("?ok?")
        confirm_and_report()

    for update in get_updates():
        offset = update["update_id"] + 1
        msg = update.get("message", {})
        if msg.get("chat", {}).get("id") != CHAT_ID:
            continue

        location_data = msg.get("location")
        if location_data:
            lat, lon = location_data.get("latitude"), location_data.get("longitude")
            send(f"Location received: {lat}, {lon} -- https://maps.google.com/?q={lat},{lon}")
            continue

        voice_data = msg.get("voice")
        if voice_data:
            last_media = {
                "type": "voice",
                "file_id": voice_data["file_id"],
                "mime_type": voice_data.get("mime_type", "audio/ogg"),
            }
            send("Voice message received. Type /send to email it as an attachment.")
            continue

        photo_data = msg.get("photo")
        if photo_data:
            largest = photo_data[-1]  # photo sizes are ordered smallest to largest
            last_media = {"type": "photo", "file_id": largest["file_id"], "mime_type": "image/jpeg"}
            send("Photo received. Type /send to email it as an attachment.")
            continue

        text = msg.get("text", "").strip().lower()
        command = text.split()[0] if text else ""
        parameters = text.split()[1:] if len(text.split()) > 1 else []

        if command in COMMANDS:
            try:
                COMMANDS[command](parameters, update)
            except Exception as e:
                send(f"Error: {e}")