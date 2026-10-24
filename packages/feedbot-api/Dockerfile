FROM python:3.14-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY packages/feedbot-core /app/packages/feedbot-core
COPY packages/feedbot-api /app/packages/feedbot-api
COPY alembic /app/alembic
COPY alembic.ini /app/alembic.ini
COPY scripts /app/scripts

RUN pip install /app/packages/feedbot-core /app/packages/feedbot-api

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn feedbot_api.app:app --host 0.0.0.0 --port 8000"]
