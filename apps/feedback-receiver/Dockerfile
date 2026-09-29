FROM python:3.11-slim

WORKDIR /opt/feedback-receiver
COPY pyproject.toml ./
COPY receiver ./receiver
RUN pip install --no-cache-dir . && useradd --system --home-dir /opt/feedback-receiver feedback
USER feedback

EXPOSE 8787
CMD ["uvicorn", "receiver.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers", "--forwarded-allow-ips", "*"]
