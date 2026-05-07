#!/usr/bin/env bash
# refresh_pipeline.sh — Phase 1D + 1E refresh.
#
# Runs the aggregation summarizer (one Claude call per active product) and
# regenerates dashboard_data.json. Designed for Railway scheduled jobs.
#
# Exit codes:
#   0  both steps succeeded
#   1  summarizer failed
#   2  dashboard generator failed
#
# Required env: DATABASE_URL, ANTHROPIC_API_KEY (Claude call falls back to a
# deterministic narrative if the key is missing or the call fails).

set -euo pipefail

cd "$(dirname "$0")/.."

echo "[refresh_pipeline] $(date -u +%Y-%m-%dT%H:%M:%SZ) starting"

if ! python -m aggregation.summarizer; then
    echo "[refresh_pipeline] summarizer failed" >&2
    exit 1
fi

if ! python -m dashboard.pulse_dashboard; then
    echo "[refresh_pipeline] dashboard generator failed" >&2
    exit 2
fi

echo "[refresh_pipeline] $(date -u +%Y-%m-%dT%H:%M:%SZ) done"
