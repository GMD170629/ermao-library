FROM python:3.11.15-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

WORKDIR /app/apps/api-python

RUN apt-get update \
  && apt-get install -y --no-install-recommends libmobi-tools ffmpeg unar ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY apps/api-python/pyproject.toml apps/api-python/uv.lock ./
COPY apps/api-python/app ./app

RUN pip install --no-cache-dir . \
  && python -m compileall -q app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
