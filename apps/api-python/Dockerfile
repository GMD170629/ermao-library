FROM python:3.11.15-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PG_MAJOR=18

WORKDIR /app/apps/api-python

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
  && install -d /usr/share/postgresql-common/pgdg \
  && curl --fail --show-error --silent \
      https://www.postgresql.org/media/keys/ACCC4CF8.asc \
      | gpg --dearmor -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg \
  && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.gpg] https://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
      > /etc/apt/sources.list.d/pgdg.list \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
      libmobi-tools ffmpeg postgresql-client-18 \
  && rm -rf /var/lib/apt/lists/*

COPY apps/api-python/pyproject.toml apps/api-python/uv.lock ./
COPY apps/api-python/appv2 ./appv2
COPY apps/api-python/alembic-v2.ini ./alembic-v2.ini
COPY apps/api-python/migrations-v2 ./migrations-v2

RUN pip install --no-cache-dir . \
  && python -m compileall -q appv2

EXPOSE 8000

CMD ["sh", "-c", "python -m appv2.entrypoints.migrate && exec uvicorn appv2.entrypoints.api:app --host 0.0.0.0 --port 8000"]
