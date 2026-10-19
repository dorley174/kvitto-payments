FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements.txt

RUN groupadd --gid 10001 api \
    && useradd --uid 10001 --gid api --no-create-home api \
    && mkdir -p /app/data \
    && chown api:api /app/data

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

USER api

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
