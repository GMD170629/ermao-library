FROM debian:bookworm-slim AS mobi-core-builder

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential cmake zlib1g-dev \
  && rm -rf /var/lib/apt/lists/*

COPY apps/mobile/native/mobi-core /src/mobi-core
RUN cmake -S /src/mobi-core -B /build/mobi-core \
      -DERMAO_MOBI_BUILD_TESTS=OFF \
      -DERMAO_MOBI_BUILD_FUZZER=OFF \
  && cmake --build /build/mobi-core --config Release --target ermao_mobi_core_shared

FROM python:3.11.15-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  ERMAO_MOBI_CORE_LIBRARY=/usr/local/lib/libermao_mobi_core.so

WORKDIR /app/apps/api-python

RUN apt-get update \
  && apt-get install -y --no-install-recommends libmobi-tools ffmpeg unar ca-certificates \
  && rm -rf /var/lib/apt/lists/*

COPY apps/api-python/pyproject.toml apps/api-python/uv.lock ./
COPY apps/api-python/app ./app
COPY --from=mobi-core-builder /build/mobi-core/libermao_mobi_core.so /usr/local/lib/libermao_mobi_core.so
COPY --from=mobi-core-builder /src/mobi-core/LICENSE /usr/share/licenses/shuku-mobi-core/LICENSE
COPY --from=mobi-core-builder /src/mobi-core/UPSTREAM.md /usr/share/licenses/shuku-mobi-core/UPSTREAM.md
COPY --from=mobi-core-builder /src/mobi-core /usr/share/shuku/source/mobi-core

RUN pip install --no-cache-dir . \
  && python -m compileall -q app

EXPOSE 8000

CMD ["sh", "-c", "python -m app.bootstrap.startup_data_migrations && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
