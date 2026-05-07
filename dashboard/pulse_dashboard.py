"""Phase 1E — dashboard data generator.

Reads recent events directly from Postgres + the latest insights JSON written
by the Phase 1D summarizer, and produces dashboard_data.json. The static HTML
in dashboard/index.html reads that JSON.

Usage:
    python -m dashboard.pulse_dashboard
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("pulsewise.dashboard")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSIGHTS_PATH = ROOT / "data" / "insights_summary.json"
DEFAULT_DASHBOARD_PATH = ROOT / "data" / "dashboard_data.json"

LIVE_FEED_LIMIT = 50


def _live_feed(conn: psycopg.Connection, limit: int) -> list[dict[str, Any]]:
    cols = [
        "event_id", "product", "event_type", "timestamp", "session_id",
        "model_provider", "confidence", "latency_ms", "cost_usd",
        "outcome", "error_code",
    ]
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {', '.join(cols)} FROM pulse_events "
            f"ORDER BY timestamp DESC LIMIT %s;",
            (limit,),
        )
        rows = cur.fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(zip(cols, row))
        if isinstance(d.get("timestamp"), datetime):
            d["timestamp"] = d["timestamp"].isoformat()
        if d.get("cost_usd") is not None:
            d["cost_usd"] = float(d["cost_usd"])
        if d.get("event_id") is not None:
            d["event_id"] = str(d["event_id"])
        out.append(d)
    return out


def _product_health(conn: psycopg.Connection) -> dict[str, dict[str, Any]]:
    """Last 1h per product: success rate, avg latency, cost/hour."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                product,
                COUNT(*) AS total,
                SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successes,
                AVG(latency_ms)::float AS avg_latency,
                SUM(cost_usd)::float AS hourly_cost
            FROM pulse_events
            WHERE timestamp > NOW() - INTERVAL '1 hour'
            GROUP BY product;
            """
        )
        rows = cur.fetchall()

    health: dict[str, dict[str, Any]] = {}
    for product, total, successes, avg_latency, hourly_cost in rows:
        total = int(total or 0)
        successes = int(successes or 0)
        health[product] = {
            "total_events_last_hour": total,
            "success_rate": (successes / total) if total else None,
            "avg_latency_ms": avg_latency,
            "cost_per_hour_usd": hourly_cost,
        }
    return health


def _load_insights(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"generated_at": None, "products": {}}
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        logger.warning("could not read insights file %s: %s", path, exc)
        return {"generated_at": None, "products": {}}


def generate(
    database_url: Optional[str] = None,
    insights_path: Path = DEFAULT_INSIGHTS_PATH,
    output_path: Path = DEFAULT_DASHBOARD_PATH,
    live_feed_limit: int = LIVE_FEED_LIMIT,
) -> Path:
    db_url = database_url or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    with psycopg.connect(db_url, autocommit=True) as conn:
        live = _live_feed(conn, live_feed_limit)
        health = _product_health(conn)

    insights_payload = _load_insights(insights_path)

    products_section: dict[str, dict[str, Any]] = {}
    seen = set(health.keys()) | set((insights_payload.get("products") or {}).keys())
    for product in sorted(seen):
        h = health.get(product, {})
        ins = (insights_payload.get("products") or {}).get(product, {})
        products_section[product] = {
            "health": h,
            "insights": {
                "narrative": ins.get("narrative"),
                "recommendations": ins.get("recommendations") or [],
                "anomalies": ins.get("anomalies") or [],
                "period_start": ins.get("period_start"),
                "period_end": ins.get("period_end"),
                "total_events": ins.get("total_events"),
                "p95_latency_ms": ins.get("p95_latency_ms"),
                "success_rate": ins.get("success_rate"),
            },
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "insights_generated_at": insights_payload.get("generated_at"),
        "live_feed": live,
        "products": products_section,
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".dashboard_", suffix=".tmp", dir=str(output_path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, output_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

    logger.info("wrote %s (%d events, %d products)", output_path, len(live), len(products_section))
    return output_path


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="PulseWise dashboard data generator")
    parser.add_argument("--insights", type=Path, default=DEFAULT_INSIGHTS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_DASHBOARD_PATH)
    parser.add_argument("--limit", type=int, default=LIVE_FEED_LIMIT)
    args = parser.parse_args()

    out = generate(
        insights_path=args.insights,
        output_path=args.output,
        live_feed_limit=args.limit,
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
