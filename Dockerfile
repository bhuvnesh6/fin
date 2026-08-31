# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

# Prevents Python from writing .pyc files / buffering stdout, keeps builds
# reproducible regardless of the host's pip config.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first so this layer is cached across code changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

COPY app.py rocket_physics.py schemas.py ./
COPY static/ ./static/
COPY templates/ ./templates/

# Run as a non-root user.
RUN useradd --create-home --uid 1000 fin && chown -R fin:fin /app
USER fin

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

# gunicorn, not the Flask dev server - this is what actually gets deployed.
# 2 workers is a sane default for this workload (the optimizer is CPU-bound
# and holds a worker for a couple of seconds per request); tune with the
# WEB_CONCURRENCY env var if needed.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "app:app"]
