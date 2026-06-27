FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    supervisor \
    cron \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --root-user-action=ignore --upgrade pip && \
    pip install --no-cache-dir --root-user-action=ignore requests fastapi uvicorn

WORKDIR /app

# Pull scripts directly from standalone folders.
# Run from project root: docker build -f docker/Dockerfile -t chaperon .
COPY standalone/telegram-bot/telegram-bot.py .
COPY standalone/chaperon-api/chaperon-api.py .
COPY standalone/telegram-cron/telegram-cron.py .

COPY docker/supervisord.conf /etc/supervisor/conf.d/chaperon.conf
COPY docker/crontab /etc/cron.d/chaperon-cron

RUN chmod 0644 /etc/cron.d/chaperon-cron && crontab /etc/cron.d/chaperon-cron

EXPOSE 8001

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
