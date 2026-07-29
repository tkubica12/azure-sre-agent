# PulseMart demo workload image.
#
# Built exclusively via `az acr build` (see AGENTS.md: "a local Docker daemon
# is not required"; PLAN.md environment facts confirm no local Docker
# daemon). This Dockerfile is still used locally for `docker build --check`
# style linting and for anyone who does have a daemon.

FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pulsemart ./pulsemart

RUN useradd --no-create-home --uid 10001 pulsemart
USER pulsemart

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]

CMD ["uvicorn", "pulsemart.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
