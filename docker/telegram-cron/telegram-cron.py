#!/usr/bin/env python3
"""
telegram-cron.py

Triggers the "?ok?" confirmation flow in telegram-bot.py by hitting its
local-only HTTP listener (127.0.0.1:8765/ok-trigger). No Telegram API
call, no token, no config file needed -- just a local request to the
already-running bot process. Meant to be run from cron or a systemd timer.

Exit codes:
  0 - trigger delivered successfully
  1 - request failed (listener down, connection error, non-2xx response)
"""
import requests, sys

TRIGGER_URL = "http://127.0.0.1:8765/ok-trigger"

try:
    r = requests.get(TRIGGER_URL, timeout=5)
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
    sys.exit(1)

if not r.ok:
    print(f"Trigger failed: {r.status_code} {r.text}")
    sys.exit(1)

sys.exit(0)