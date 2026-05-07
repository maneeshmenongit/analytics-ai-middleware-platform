# PulseWise — production image.
#
# Builds a single image that can run either the collector (default CMD) or
# the aggregator (override command at deploy time). Two Railway services,
# one image.

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg's binary wheel ships libpq; slim image only needs curl for the
# inline healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so the layer caches across code changes.
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy the rest of the project. .dockerignore prunes .venv, tests, .git, etc.
COPY . .

# Non-root user for runtime. /app/data must be writable so the aggregator can
# write insights_summary.json and dashboard_data.json.
RUN useradd --create-home --shell /bin/bash pulsewise \
    && mkdir -p /app/data \
    && chown -R pulsewise:pulsewise /app
USER pulsewise

EXPOSE 8400

# Healthcheck mirrors railway.toml's /health probe so docker-compose / local
# `docker run` get the same signal.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8400}/health" || exit 1

# Default: run the collector. Override at deploy time for the aggregator:
#   command: bash scripts/refresh_pipeline.sh
CMD ["sh", "-c", "uvicorn ingestion.collector:app --host 0.0.0.0 --port ${PORT:-8400} --workers 2 --proxy-headers"]
