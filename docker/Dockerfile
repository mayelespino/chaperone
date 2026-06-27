FROM python:3.11-slim

# Install supervisord and cron
RUN apt-get update && apt-get install -y \
    supervisor \
    cron \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --no-cache-dir requests fastapi uvicorn

WORKDIR /app

# Copy application files
COPY telegram-bot.py .
COPY chaperon-api.py .
COPY telegram-cron.py .

# Copy supervisord config and crontab
COPY supervisord.conf /etc/supervisor/conf.d/chaperon.conf
COPY crontab /etc/cron.d/chaperon-cron

# Set correct permissions on crontab
RUN chmod 0644 /etc/cron.d/chaperon-cron && crontab /etc/cron.d/chaperon-cron

# telegram-bot.ini is NOT baked into the image -- it is mounted at runtime
# via: docker run -v /path/to/telegram-bot.ini:/app/telegram-bot.ini ...
# This keeps credentials out of the image entirely.

EXPOSE 8001

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
