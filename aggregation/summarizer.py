"""Phase 1D — aggregation summarizer.

Reads pulse_events for the last 24 hours, computes metrics per product,
detects anomalies vs. a 7-day baseline, and makes ONE Claude call per product
to produce a narrative + recommendations. Writes data/insights_summary.json.

Usage:
    python -m aggregation.summarizer
    python aggregation/summarizer.py [--product voicewise]

Hard constraints respected:
- Exactly one Claude call per product per run (zero if Claude unavailable).
- All SQL aggregations are pure SQL — no LLM involvement.
- Failures (Claude timeout, bad JSON) fall back to a deterministic narrative;
  the job never crashes the pipeline.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger("pulsewise.summarizer")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INSIGHTS_PATH = ROOT / "data" / "insights_summary.json"

ANOMALY_LATENCY_THRESHOLD = 1.40  # 40% above 7-day baseline
ANOMALY_FAILURE_RATE = 0.10
LOOKBACK_HOURS_DEFAULT = 24
BASELINE_DAYS_DEFAULT = 7

CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 600

SYSTEM_PROMPT = """You are a product analytics advisor for an AI startup.
Given aggregated metrics from the last 24 hours, write:
1. A 3-5 sentence narrative describing what happened and what's notable
2. 2-3 specific, actionable recommendations

Be concrete — reference actual numbers. Flag anomalies clearly.
Return ONLY JSON: {"narrative": "...", "recommendations": ["...", "..."]}"""


@dataclass
class ProductInsights:
    product: str
    period_start: datetime
    period_end: datetime

    total_events: int
    events_by_type: dict[str, int]
    active_sessions: int

    avg_latency_ms: Optional[float]
    p95_latency_ms: Optional[float]
    avg_confidence: Optional[float]
    total_cost_usd: Optional[float]

    success_rate: float
    failure_rate: float
    retry_rate: float

    anomalies: list[str] = field(default_factory=list)
    narrative: str = ""
    recommendations: list[str] = field(default_factory=list)

    def to_serializable(self) -> dict[str, Any]:
        d = asdict(self)
        d["period_start"] = self.period_start.isoformat()
        d["period_end"] = self.period_end.isoformat()
        return d


# ---------- SQL aggregation ----------

def _list_active_products(conn: psycopg.Connection, lookback_hours: int) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT product
            FROM pulse_events
            WHERE timestamp > NOW() - %s::interval
            ORDER BY product;
            """,
            (f"{lookback_hours} hours",),
        )
        return [row[0] for row in cur.fetchall()]


def _aggregate_product(
    conn: psycopg.Connection,
    product: str,
    period_start: datetime,
    period_end: datetime,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total,
                COUNT(DISTINCT session_id) AS sessions,
                AVG(latency_ms)::float AS avg_latency,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::float AS p95_latency,
                AVG(confidence)::float AS avg_confidence,
                SUM(cost_usd)::float AS total_cost,
                SUM(CASE WHEN outcome='success' THEN 1 ELSE 0 END) AS successes,
                SUM(CASE WHEN outcome='failure' THEN 1 ELSE 0 END) AS failures,
                SUM(CASE WHEN outcome='retry'   THEN 1 ELSE 0 END) AS retries
            FROM pulse_events
            WHERE product = %s
              AND timestamp >= %s
              AND timestamp <  %s;
            """,
            (product, period_start, period_end),
        )
        row = cur.fetchone()
        total = row[0] or 0

        cur.execute(
            """
            SELECT event_type, COUNT(*) AS n
            FROM pulse_events
            WHERE product = %s
              AND timestamp >= %s
              AND timestamp <  %s
            GROUP BY event_type
            ORDER BY n DESC;
            """,
            (product, period_start, period_end),
        )
        events_by_type = {et: int(n) for et, n in cur.fetchall()}

        cur.execute(
            """
            SELECT error_code, COUNT(*) AS n
            FROM pulse_events
            WHERE product = %s
              AND outcome = 'failure'
              AND error_code IS NOT NULL
              AND timestamp >= %s
              AND timestamp <  %s
            GROUP BY error_code
            ORDER BY n DESC
            LIMIT 5;
            """,
            (product, period_start, period_end),
        )
        top_errors = [{"code": code, "count": int(n)} for code, n in cur.fetchall()]

    successes = int(row[6] or 0)
    failures = int(row[7] or 0)
    retries = int(row[8] or 0)

    return {
        "total": int(total),
        "sessions": int(row[1] or 0),
        "avg_latency": row[2],
        "p95_latency": row[3],
        "avg_confidence": row[4],
        "total_cost": row[5],
        "successes": successes,
        "failures": failures,
        "retries": retries,
        "events_by_type": events_by_type,
        "top_errors": top_errors,
    }


def _baseline_p95_latency(
    conn: psycopg.Connection,
    product: str,
    baseline_end: datetime,
    baseline_days: int,
) -> Optional[float]:
    baseline_start = baseline_end - timedelta(days=baseline_days)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::float
            FROM pulse_events
            WHERE product = %s
              AND timestamp >= %s
              AND timestamp <  %s;
            """,
            (product, baseline_start, baseline_end),
        )
        v = cur.fetchone()
        return v[0] if v and v[0] is not None else None


# ---------- anomaly detection ----------

def _detect_anomalies(
    metrics: dict[str, Any],
    baseline_p95: Optional[float],
) -> list[str]:
    anomalies: list[str] = []
    p95 = metrics.get("p95_latency")
    if baseline_p95 and p95 and baseline_p95 > 0:
        ratio = p95 / baseline_p95
        if ratio >= ANOMALY_LATENCY_THRESHOLD:
            pct = (ratio - 1.0) * 100.0
            anomalies.append(
                f"p95 latency {p95:.0f}ms is {pct:.0f}% above 7-day baseline "
                f"({baseline_p95:.0f}ms)"
            )

    total = metrics["total"]
    if total > 0:
        failure_rate = metrics["failures"] / total
        if failure_rate >= ANOMALY_FAILURE_RATE:
            anomalies.append(
                f"failure rate {failure_rate*100:.1f}% "
                f"({metrics['failures']}/{total}) exceeds {ANOMALY_FAILURE_RATE*100:.0f}% threshold"
            )

    top = metrics.get("top_errors") or []
    if top:
        leader = top[0]
        anomalies.append(
            f"top error code: {leader['code']} ({leader['count']} occurrences)"
        )

    return anomalies


# ---------- Claude narrative ----------

def _fallback_narrative(insight: ProductInsights) -> tuple[str, list[str]]:
    parts = [
        f"{insight.product} processed {insight.total_events} events across "
        f"{insight.active_sessions} sessions in the last 24h.",
    ]
    if insight.p95_latency_ms is not None:
        parts.append(f"p95 latency was {insight.p95_latency_ms:.0f}ms.")
    if insight.avg_confidence is not None:
        parts.append(f"avg model confidence {insight.avg_confidence:.2f}.")
    if insight.total_cost_usd:
        parts.append(f"total spend ${insight.total_cost_usd:.4f}.")
    parts.append(
        f"success rate {insight.success_rate*100:.1f}%, "
        f"failure rate {insight.failure_rate*100:.1f}%."
    )
    narrative = " ".join(parts)

    recs: list[str] = []
    if insight.failure_rate > 0.05:
        recs.append("Investigate top failure source — failure rate above 5%.")
    if insight.p95_latency_ms and insight.p95_latency_ms > 1000:
        recs.append("p95 latency above 1s — review slow event types.")
    if not recs:
        recs.append("No urgent issues; continue current monitoring cadence.")
    return narrative, recs


def _call_claude(
    client,
    product: str,
    period_start: datetime,
    period_end: datetime,
    metrics_dict: dict[str, Any],
    anomalies: list[str],
) -> tuple[str, list[str]]:
    user = (
        f"Product: {product}\n"
        f"Period: {period_start.isoformat()} to {period_end.isoformat()}\n\n"
        f"Metrics:\n{json.dumps(metrics_dict, indent=2, default=str)}\n\n"
        f"Anomalies detected:\n{json.dumps(anomalies, indent=2)}"
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
    )

    text_parts: list[str] = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if text:
            text_parts.append(text)
    raw = "".join(text_parts).strip()

    raw = _strip_code_fence(raw)
    parsed = json.loads(raw)
    narrative = str(parsed.get("narrative") or "").strip()
    recs_raw = parsed.get("recommendations") or []
    if not isinstance(recs_raw, list):
        raise ValueError("recommendations is not a list")
    recommendations = [str(r).strip() for r in recs_raw if str(r).strip()]
    if not narrative:
        raise ValueError("empty narrative")
    return narrative, recommendations


def _strip_code_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


# ---------- top-level run ----------

def summarize_product(
    conn: psycopg.Connection,
    product: str,
    period_end: datetime,
    lookback_hours: int = LOOKBACK_HOURS_DEFAULT,
    baseline_days: int = BASELINE_DAYS_DEFAULT,
    anthropic_client=None,
) -> ProductInsights:
    period_start = period_end - timedelta(hours=lookback_hours)

    metrics = _aggregate_product(conn, product, period_start, period_end)
    baseline_p95 = _baseline_p95_latency(conn, product, period_end, baseline_days)
    anomalies = _detect_anomalies(metrics, baseline_p95)

    total = metrics["total"]
    if total > 0:
        success_rate = metrics["successes"] / total
        failure_rate = metrics["failures"] / total
        retry_rate = metrics["retries"] / total
    else:
        success_rate = failure_rate = retry_rate = 0.0

    insight = ProductInsights(
        product=product,
        period_start=period_start,
        period_end=period_end,
        total_events=total,
        events_by_type=metrics["events_by_type"],
        active_sessions=metrics["sessions"],
        avg_latency_ms=metrics["avg_latency"],
        p95_latency_ms=metrics["p95_latency"],
        avg_confidence=metrics["avg_confidence"],
        total_cost_usd=metrics["total_cost"],
        success_rate=success_rate,
        failure_rate=failure_rate,
        retry_rate=retry_rate,
        anomalies=anomalies,
    )

    metrics_for_claude = {
        "total_events": total,
        "active_sessions": insight.active_sessions,
        "events_by_type": insight.events_by_type,
        "avg_latency_ms": insight.avg_latency_ms,
        "p95_latency_ms": insight.p95_latency_ms,
        "avg_confidence": insight.avg_confidence,
        "total_cost_usd": insight.total_cost_usd,
        "success_rate": round(success_rate, 4),
        "failure_rate": round(failure_rate, 4),
        "retry_rate": round(retry_rate, 4),
        "top_errors": metrics["top_errors"],
        "baseline_p95_latency_ms": baseline_p95,
    }

    narrative, recommendations = "", []
    if anthropic_client is not None and total > 0:
        try:
            narrative, recommendations = _call_claude(
                anthropic_client, product, period_start, period_end,
                metrics_for_claude, anomalies,
            )
        except Exception as exc:
            logger.warning("claude call failed for %s, falling back: %s", product, exc)

    if not narrative:
        narrative, recommendations = _fallback_narrative(insight)

    insight.narrative = narrative
    insight.recommendations = recommendations
    return insight


def write_insights(
    insights: list[ProductInsights],
    path: Path = DEFAULT_INSIGHTS_PATH,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "products": {ins.product: ins.to_serializable() for ins in insights},
    }
    fd, tmp = tempfile.mkstemp(prefix=".insights_", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def _build_anthropic_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping Claude narrative")
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as exc:
        logger.warning("failed to init Anthropic client: %s", exc)
        return None


def run(
    database_url: Optional[str] = None,
    products: Optional[list[str]] = None,
    output_path: Path = DEFAULT_INSIGHTS_PATH,
    lookback_hours: int = LOOKBACK_HOURS_DEFAULT,
    baseline_days: int = BASELINE_DAYS_DEFAULT,
    anthropic_client=None,
    period_end: Optional[datetime] = None,
) -> list[ProductInsights]:
    db_url = database_url or os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set")

    if anthropic_client is None:
        anthropic_client = _build_anthropic_client()
    if period_end is None:
        period_end = datetime.now(timezone.utc)

    results: list[ProductInsights] = []
    with psycopg.connect(db_url, autocommit=True) as conn:
        if products is None:
            products = _list_active_products(conn, lookback_hours)
        for product in products:
            logger.info("summarizing %s", product)
            results.append(summarize_product(
                conn, product, period_end,
                lookback_hours=lookback_hours,
                baseline_days=baseline_days,
                anthropic_client=anthropic_client,
            ))
    write_insights(results, output_path)
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="PulseWise aggregation summarizer")
    parser.add_argument("--product", action="append", help="Limit to a specific product (repeatable)")
    parser.add_argument("--lookback-hours", type=int, default=LOOKBACK_HOURS_DEFAULT)
    parser.add_argument("--baseline-days", type=int, default=BASELINE_DAYS_DEFAULT)
    parser.add_argument("--output", type=Path, default=DEFAULT_INSIGHTS_PATH)
    args = parser.parse_args()

    insights = run(
        products=args.product,
        output_path=args.output,
        lookback_hours=args.lookback_hours,
        baseline_days=args.baseline_days,
    )
    print(f"wrote {args.output} with {len(insights)} product(s)")
    for ins in insights:
        print(f"  - {ins.product}: {ins.total_events} events, "
              f"{len(ins.anomalies)} anomalies, "
              f"narrative={ins.narrative[:60]!r}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
