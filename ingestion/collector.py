"""Phase 1B — FastAPI ingestion collector.

Endpoints:
  POST   /events             ingest single event or batch (max 100)
  GET    /health             returns DB connection status
  GET    /events/recent      last N events for a product
  GET    /insights/{product} latest aggregated insights (stub until 1D)
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from core.event_schema import PulseEvent, validate_event
from ingestion.db import apply_migrations, healthcheck, make_pool

logger = logging.getLogger("pulsewise.collector")

MAX_BATCH_SIZE = 100


def _parse_event(payload: dict[str, Any]) -> tuple[Optional[PulseEvent], list[str]]:
    """Build a PulseEvent from a JSON dict. Returns (event, errors)."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return None, ["event must be a JSON object"]

    try:
        ts_raw = payload.get("timestamp")
        if isinstance(ts_raw, str):
            timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            timestamp = ts_raw
        elif ts_raw is None:
            timestamp = datetime.now().astimezone()
        else:
            return None, [f"timestamp must be ISO string, got {type(ts_raw).__name__}"]
    except (ValueError, TypeError) as exc:
        return None, [f"invalid timestamp: {exc}"]

    try:
        event = PulseEvent(
            product=str(payload.get("product", "")),
            event_type=str(payload.get("event_type", "")),
            session_id=str(payload.get("session_id", "")),
            outcome=str(payload.get("outcome", "success")),
            user_id=payload.get("user_id"),
            model_name=payload.get("model_name"),
            model_provider=payload.get("model_provider"),
            confidence=payload.get("confidence"),
            latency_ms=payload.get("latency_ms"),
            tokens_used=payload.get("tokens_used"),
            cost_usd=payload.get("cost_usd"),
            error_code=payload.get("error_code"),
            retry_count=int(payload.get("retry_count") or 0),
            context=payload.get("context") or {},
            tags=list(payload.get("tags") or []),
            event_id=payload.get("event_id") or PulseEvent.__dataclass_fields__["event_id"].default_factory(),
            timestamp=timestamp,
        )
    except (TypeError, ValueError) as exc:
        return None, [f"failed to construct event: {exc}"]

    errs = validate_event(event)
    if errs:
        return None, errs
    return event, []


def _insert_events(pool: ConnectionPool, events: list[PulseEvent]) -> int:
    """Insert events. ON CONFLICT DO NOTHING — duplicate event_ids are silently
    skipped (idempotent). Returns count of newly inserted rows."""
    sql = """
    INSERT INTO pulse_events (
        event_id, product, event_type, timestamp, session_id, user_id,
        model_name, model_provider, confidence, latency_ms, tokens_used, cost_usd,
        outcome, error_code, retry_count, context, tags
    ) VALUES (
        %(event_id)s, %(product)s, %(event_type)s, %(timestamp)s, %(session_id)s, %(user_id)s,
        %(model_name)s, %(model_provider)s, %(confidence)s, %(latency_ms)s, %(tokens_used)s, %(cost_usd)s,
        %(outcome)s, %(error_code)s, %(retry_count)s, %(context)s, %(tags)s
    )
    ON CONFLICT (event_id) DO NOTHING;
    """
    inserted = 0
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for ev in events:
                cur.execute(sql, {
                    "event_id": ev.event_id,
                    "product": ev.product,
                    "event_type": ev.event_type,
                    "timestamp": ev.timestamp,
                    "session_id": ev.session_id,
                    "user_id": ev.user_id,
                    "model_name": ev.model_name,
                    "model_provider": ev.model_provider,
                    "confidence": ev.confidence,
                    "latency_ms": ev.latency_ms,
                    "tokens_used": ev.tokens_used,
                    "cost_usd": ev.cost_usd,
                    "outcome": ev.outcome,
                    "error_code": ev.error_code,
                    "retry_count": ev.retry_count,
                    "context": Jsonb(ev.context or {}),
                    "tags": ev.tags or [],
                })
                inserted += cur.rowcount
    return inserted


def _row_to_dict(row, columns: list[str]) -> dict[str, Any]:
    out = dict(zip(columns, row))
    if isinstance(out.get("timestamp"), datetime):
        out["timestamp"] = out["timestamp"].isoformat()
    if isinstance(out.get("ingested_at"), datetime):
        out["ingested_at"] = out["ingested_at"].isoformat()
    if out.get("cost_usd") is not None:
        out["cost_usd"] = float(out["cost_usd"])
    return out


def create_app(database_url: Optional[str] = None, run_migrations: bool = True) -> FastAPI:
    db_url = database_url or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set and no database_url passed to create_app")

    if run_migrations:
        apply_migrations(db_url)

    pool: ConnectionPool = make_pool(db_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        pool.close()

    app = FastAPI(title="PulseWise Collector", version="0.1.0", lifespan=lifespan)
    app.state.pool = pool

    @app.post("/events")
    async def post_events(request: Request):
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}")

        if isinstance(body, dict):
            raw_events: list[dict[str, Any]] = [body]
        elif isinstance(body, list):
            raw_events = body
        else:
            raise HTTPException(status_code=400, detail="body must be a JSON object or array")

        if len(raw_events) == 0:
            raise HTTPException(status_code=400, detail="empty batch")
        if len(raw_events) > MAX_BATCH_SIZE:
            raise HTTPException(
                status_code=422,
                detail=f"batch size {len(raw_events)} exceeds max {MAX_BATCH_SIZE}",
            )

        valid: list[PulseEvent] = []
        errors: list[dict[str, Any]] = []
        for idx, raw in enumerate(raw_events):
            event, errs = _parse_event(raw if isinstance(raw, dict) else {})
            if event is None:
                errors.append({"index": idx, "errors": errs})
            else:
                valid.append(event)

        try:
            inserted = _insert_events(pool, valid)
        except psycopg.Error as exc:
            logger.exception("db insert failed")
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")

        return {
            "accepted": inserted,
            "rejected": len(errors),
            "errors": errors,
        }

    @app.get("/health")
    async def health():
        ok = healthcheck(pool)
        status = "ok" if ok else "degraded"
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": status, "db": ok},
        )

    @app.get("/events/recent")
    async def recent(
        product: Optional[str] = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        cols = [
            "event_id", "product", "event_type", "timestamp", "session_id",
            "user_id", "model_name", "model_provider", "confidence",
            "latency_ms", "tokens_used", "cost_usd", "outcome", "error_code",
            "retry_count", "context", "tags", "ingested_at",
        ]
        select = f"SELECT {', '.join(cols)} FROM pulse_events"
        where = ""
        params: tuple = ()
        if product:
            where = " WHERE product = %s"
            params = (product,)
        sql = f"{select}{where} ORDER BY timestamp DESC LIMIT %s;"
        params = params + (limit,)

        try:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
        except psycopg.Error as exc:
            logger.exception("db query failed")
            raise HTTPException(status_code=503, detail=f"database unavailable: {exc}")

        return {"events": [_row_to_dict(r, cols) for r in rows]}

    @app.get("/insights/{product}")
    async def insights(product: str):
        path = Path(os.getenv(
            "PULSEWISE_INSIGHTS_PATH",
            str(Path(__file__).resolve().parent.parent / "data" / "insights_summary.json"),
        ))
        if not path.exists():
            return {
                "product": product,
                "narrative": None,
                "recommendations": [],
                "generated_at": None,
                "note": "no insights yet — run `python -m aggregation.summarizer`",
            }
        try:
            payload = json.loads(path.read_text())
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"insights file unreadable: {exc}")
        product_block = (payload.get("products") or {}).get(product)
        if product_block is None:
            return {
                "product": product,
                "narrative": None,
                "recommendations": [],
                "generated_at": payload.get("generated_at"),
                "note": "no insights for this product in latest run",
            }
        return {
            **product_block,
            "generated_at": payload.get("generated_at"),
        }

    # Mount static dashboard so it is reachable at <host>/dashboard/index.html
    # and dashboard_data.json at <host>/data/dashboard_data.json (same-origin
    # fetch, which is what dashboard/index.html expects).
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles

    repo_root = Path(__file__).resolve().parent.parent
    dashboard_dir = repo_root / "dashboard"
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if dashboard_dir.is_dir():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")
    app.mount("/data", StaticFiles(directory=str(data_dir)), name="data")

    @app.get("/", include_in_schema=False)
    async def _root():
        return RedirectResponse(url="/dashboard/")

    return app


# Module-level app for uvicorn: `uvicorn ingestion.collector:app`
# Load .env at import so the DATABASE_URL is visible when uvicorn imports us.
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except ImportError:
    pass

if not os.getenv("DATABASE_URL"):
    raise RuntimeError(
        "DATABASE_URL not set. Add it to .env or export it before running the collector."
    )
app: FastAPI = create_app()
