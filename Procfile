web: uvicorn ingestion.collector:app --host 0.0.0.0 --port ${PORT:-8400} --workers 2 --proxy-headers
aggregator: bash scripts/refresh_pipeline.sh
