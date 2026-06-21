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


def ping():
    return "PONG@chap"


def echo():
    return "ECHO"


COMMANDS = {
    "/ping": ping(),
    "/echo": echo(),
}

######################################################################
# Telegram helpers
######################################################################


def send(text):
    try:
        session.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": text},
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        print(f"send() failed: {e}")


def send_notification_email():
    msg = EmailMessage()
    msg["Subject"] = "Chaperon Notification"
    msg["From"] = SMTP_USERNAME
    msg["To"] = NOTIFY_EMAIL
    msg.set_content(NOTIFY_MESSAGE)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as e:
        print(f"send_notification_email() failed: {e}")


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
        text = msg.get("text", "").strip().lower()
        command = text.split()[0] if text else ""
        parameters = text.split()[1:] if len(text.split()) > 1 else []

        if command == "?ok?":
            confirm_and_report()
        elif command in COMMANDS:
            try:
                result = COMMANDS[command]
                if result == "ECHO":
                    echoString = (
                        update.get("message", {}).get("from", {}).get("first_name", "")
                        + " "
                        + update.get("message", {}).get("from", {}).get("last_name", "")
                        + ": "
                        + " ".join(parameters)
                    )
                    send(echoString)
                else:
                    send(result)
            except Exception as e:
                send(f"Error: {e}")