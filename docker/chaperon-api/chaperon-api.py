#!/usr/bin/env python3
"""
chaperon-api.py

A small FastAPI service exposing a REST API for scheduling ad-hoc
confirmation checks. The first endpoint accepts an hour (0-23) and a
minute (0-59) and, at that time today, fires the same local trigger
that telegram-cron.py uses -- i.e. it hits telegram-bot.py's
127.0.0.1:8765/ok-trigger endpoint to kick off the "?ok?" confirmation
flow. No Telegram API call happens from this service directly; it
only ever talks to the already-running bot's local listener.

Run directly with:
    python3 chaperon-api.py

Or under uvicorn for production-style process management (rename the
file to use underscores -- e.g. chaperon_api.py -- if you want to
invoke it as `uvicorn chaperon_api:app`, since uvicorn imports the
module by name and hyphens aren't valid there):
    uvicorn chaperon-api:app --host 0.0.0.0 --port 8001
"""
import asyncio
import subprocess
import uuid
from datetime import datetime

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Chaperon API")

# Same endpoint telegram-cron.py hits -- this service never talks to
# Telegram directly, it just nudges the already-running bot.
TRIGGER_URL = "http://127.0.0.1:8765/ok-trigger"

# id -> asyncio.Task, kept around so a future list/cancel endpoint has
# something to work with.
scheduled_checks = {}


class AdHocCheckRequest(BaseModel):
    hour: int = Field(
        ..., ge=0, le=23, description="Hour of the day (0-23) to run the check today"
    )
    minute: int = Field(
        ..., ge=0, le=59, description="Minute of the hour (0-59) to run the check today"
    )


def fire_ok_trigger():
    """Runs in a worker thread when the scheduled time arrives."""
    try:
        r = requests.get(TRIGGER_URL, timeout=5)
        if not r.ok:
            print(f"Trigger failed: {r.status_code} {r.text}")
    except requests.exceptions.RequestException as e:
        print(f"Trigger request failed: {e}")


async def run_at(check_id: str, delay_seconds: float):
    await asyncio.sleep(delay_seconds)
    loop = asyncio.get_running_loop()
    # fire_ok_trigger() is a blocking call (requests), so it runs in
    # an executor thread rather than blocking the event loop.
    await loop.run_in_executor(None, fire_ok_trigger)
    scheduled_checks.pop(check_id, None)


@app.post("/checks")
async def add_ad_hoc_check(payload: AdHocCheckRequest):
    now = datetime.now()
    target = now.replace(hour=payload.hour, minute=payload.minute, second=0, microsecond=0)

    if target <= now:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{target.strftime('%H:%M')} has already passed today "
                f"(current server time is {now.strftime('%H:%M:%S')})."
            ),
        )

    delay_seconds = (target - now).total_seconds()
    check_id = str(uuid.uuid4())
    task = asyncio.create_task(run_at(check_id, delay_seconds))
    scheduled_checks[check_id] = task

    return {
        "id": check_id,
        "scheduled_for": target.isoformat(),
        "seconds_from_now": int(delay_seconds),
    }


@app.get("/crontab")
async def get_crontab():
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="crontab command not found on this system.")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="crontab -l timed out.")

    if result.returncode != 0:
        # Most commonly: no crontab exists yet for this user.
        return {"crontab": "", "message": result.stderr.strip() or "No crontab found."}

    return {"crontab": result.stdout}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)