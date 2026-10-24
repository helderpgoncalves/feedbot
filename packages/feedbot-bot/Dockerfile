FROM python:3.14-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY packages/feedbot-core /app/packages/feedbot-core
COPY packages/feedbot-bot /app/packages/feedbot-bot

RUN pip install /app/packages/feedbot-core /app/packages/feedbot-bot

CMD ["python", "-m", "feedbot_bot.telegram_bot"]
