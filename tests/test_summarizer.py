import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

TEST_DB_URL = os.getenv(
    "PULSEWISE_TEST_DATABASE_URL",
    "postgresql://maneeshmenon@localhost:5432/pulsewise_test",
)


def _pg_reachable(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return True
    except Exception:
        return False


if not _pg_reachable(TEST_DB_URL):
    pytest.skip(
        f"Postgres test DB not reachable at {TEST_DB_URL}",
        allow_module_level=True,
    )

from aggregation.summarizer import (  # noqa: E402
    ProductInsights,
    _detect_anomalies,
    _fallback_narrative,
    _strip_code_fence,
    run,
    summarize_product,
    write_insights,
)
from ingestion.db import apply_migrations  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _migrations():
    apply_migrations(TEST_DB_URL)


@pytest.fixture(autouse=True)
def _truncate():
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE pulse_events;")
    yield


# ---------- helpers ----------

def _seed(events: list[dict]) -> None:
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            for e in events:
                cur.execute(
                    """
                    INSERT INTO pulse_events
                      (event_id, product, event_type, timestamp, session_id, user_id,
                       model_name, model_provider, confidence, latency_ms, tokens_used,
                       cost_usd, outcome, error_code, retry_count, context, tags)
                    VALUES
                      (%(event_id)s, %(product)s, %(event_type)s, %(timestamp)s, %(session_id)s,
                       %(user_id)s, %(model_name)s, %(model_provider)s, %(confidence)s,
                       %(latency_ms)s, %(tokens_used)s, %(cost_usd)s, %(outcome)s,
                       %(error_code)s, %(retry_count)s, %(context)s::jsonb, %(tags)s);
                    """,
                    {
                        "event_id": e.get("event_id") or str(uuid.uuid4()),
                        "product": e["product"],
                        "event_type": e["event_type"],
                        "timestamp": e["timestamp"],
                        "session_id": e["session_id"],
                        "user_id": e.get("user_id"),
                        "model_name": e.get("model_name"),
                        "model_provider": e.get("model_provider"),
                        "confidence": e.get("confidence"),
                        "latency_ms": e.get("latency_ms"),
                        "tokens_used": e.get("tokens_used"),
                        "cost_usd": e.get("cost_usd"),
                        "outcome": e.get("outcome", "success"),
                        "error_code": e.get("error_code"),
                        "retry_count": e.get("retry_count", 0),
                        "context": json.dumps(e.get("context") or {}),
                        "tags": e.get("tags") or [],
                    },
                )


# ---------- pure-Python helpers ----------

class TestStripCodeFence:
    def test_no_fence(self):
        assert _strip_code_fence('{"a": 1}') == '{"a": 1}'

    def test_fence_with_language(self):
        assert _strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_bare_fence(self):
        assert _strip_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'


class TestAnomalyDetection:
    def test_no_anomalies_when_metrics_clean(self):
        metrics = {
            "total": 100, "successes": 95, "failures": 2, "retries": 3,
            "p95_latency": 100.0, "top_errors": [],
        }
        assert _detect_anomalies(metrics, baseline_p95=120.0) == []

    def test_p95_above_baseline_flagged(self):
        metrics = {
            "total": 100, "successes": 100, "failures": 0, "retries": 0,
            "p95_latency": 200.0, "top_errors": [],
        }
        result = _detect_anomalies(metrics, baseline_p95=100.0)
        assert any("p95 latency" in s and "above" in s for s in result)

    def test_failure_rate_threshold(self):
        metrics = {
            "total": 100, "successes": 80, "failures": 15, "retries": 5,
            "p95_latency": 100.0, "top_errors": [],
        }
        result = _detect_anomalies(metrics, baseline_p95=100.0)
        assert any("failure rate" in s for s in result)

    def test_top_error_surfaced(self):
        metrics = {
            "total": 10, "successes": 9, "failures": 1, "retries": 0,
            "p95_latency": 100.0, "top_errors": [{"code": "TIMEOUT", "count": 1}],
        }
        result = _detect_anomalies(metrics, baseline_p95=100.0)
        assert any("TIMEOUT" in s for s in result)

    def test_no_baseline_no_latency_anomaly(self):
        metrics = {
            "total": 100, "successes": 100, "failures": 0, "retries": 0,
            "p95_latency": 5000.0, "top_errors": [],
        }
        result = _detect_anomalies(metrics, baseline_p95=None)
        assert not any("p95 latency" in s for s in result)


class TestFallbackNarrative:
    def test_basic_fallback(self):
        ins = ProductInsights(
            product="voicewise",
            period_start=datetime.now(timezone.utc) - timedelta(hours=24),
            period_end=datetime.now(timezone.utc),
            total_events=100, events_by_type={"voice.transcription": 100},
            active_sessions=10,
            avg_latency_ms=200.0, p95_latency_ms=400.0,
            avg_confidence=0.9, total_cost_usd=0.5,
            success_rate=0.95, failure_rate=0.05, retry_rate=0.0,
        )
        narrative, recs = _fallback_narrative(ins)
        assert "voicewise" in narrative
        assert "100" in narrative
        assert recs


# ---------- SQL aggregation against real DB ----------

class TestAggregation:
    def test_counts_and_sessions(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1", "outcome": "success"},
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=2), "session_id": "s1", "outcome": "success"},
            {"product": "voicewise", "event_type": "voice.synthesis",
             "timestamp": now - timedelta(hours=3), "session_id": "s2", "outcome": "failure",
             "error_code": "PROVIDER_TIMEOUT"},
        ])
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=None)

        assert ins.total_events == 3
        assert ins.active_sessions == 2
        assert ins.events_by_type == {"voice.transcription": 2, "voice.synthesis": 1}
        assert ins.success_rate == pytest.approx(2 / 3)
        assert ins.failure_rate == pytest.approx(1 / 3)

    def test_latency_and_cost_aggregation(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "hopwise", "event_type": "recommendation.shown",
             "timestamp": now - timedelta(hours=1), "session_id": f"s{i}",
             "latency_ms": 100 + i * 10, "cost_usd": 0.001, "confidence": 0.9}
            for i in range(10)
        ])
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "hopwise", now, anthropic_client=None)

        assert ins.total_events == 10
        assert ins.avg_latency_ms is not None and 100 <= ins.avg_latency_ms <= 200
        assert ins.p95_latency_ms is not None
        assert ins.total_cost_usd == pytest.approx(0.01, rel=1e-3)
        assert ins.avg_confidence == pytest.approx(0.9)

    def test_no_events_returns_zeros_not_crash(self):
        now = datetime.now(timezone.utc)
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=None)
        assert ins.total_events == 0
        assert ins.success_rate == 0.0
        assert ins.narrative  # fallback narrative still generated


# ---------- mocked Anthropic client ----------

class FakeContentBlock:
    def __init__(self, text):
        self.text = text


class FakeResponse:
    def __init__(self, text):
        self.content = [FakeContentBlock(text)]


class FakeMessages:
    def __init__(self, response_text=None, raise_exc=None):
        self.response_text = response_text
        self.raise_exc = raise_exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        return FakeResponse(self.response_text)


class FakeAnthropic:
    def __init__(self, response_text=None, raise_exc=None):
        self.messages = FakeMessages(response_text=response_text, raise_exc=raise_exc)


class TestClaudeIntegration:
    def test_one_call_per_product(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=2), "session_id": "s2"},
        ])
        client = FakeAnthropic(response_text=json.dumps({
            "narrative": "All good.",
            "recommendations": ["Keep going.", "Watch latency."],
        }))
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=client)

        assert len(client.messages.calls) == 1
        assert ins.narrative == "All good."
        assert ins.recommendations == ["Keep going.", "Watch latency."]

    def test_claude_failure_falls_back(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
        ])
        client = FakeAnthropic(raise_exc=RuntimeError("boom"))
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=client)
        assert ins.narrative  # fallback used
        assert "voicewise" in ins.narrative

    def test_claude_invalid_json_falls_back(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
        ])
        client = FakeAnthropic(response_text="this is not JSON")
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=client)
        assert ins.narrative
        assert "voicewise" in ins.narrative

    def test_claude_handles_code_fence(self):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
        ])
        client = FakeAnthropic(response_text='```json\n{"narrative": "Fenced.", "recommendations": ["a"]}\n```')
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=client)
        assert ins.narrative == "Fenced."
        assert ins.recommendations == ["a"]

    def test_claude_skipped_when_no_events(self):
        now = datetime.now(timezone.utc)
        client = FakeAnthropic(response_text='{"narrative": "x", "recommendations": []}')
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            ins = summarize_product(conn, "voicewise", now, anthropic_client=client)
        assert len(client.messages.calls) == 0  # no Claude call when total=0
        assert ins.narrative  # fallback


# ---------- run() top-level ----------

class TestRun:
    def test_run_writes_insights_file(self, tmp_path):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
            {"product": "hopwise", "event_type": "recommendation.shown",
             "timestamp": now - timedelta(hours=2), "session_id": "s2"},
        ])
        client = FakeAnthropic(response_text=json.dumps({
            "narrative": "Yes.", "recommendations": ["x"],
        }))
        out = tmp_path / "insights.json"
        results = run(
            database_url=TEST_DB_URL,
            output_path=out,
            anthropic_client=client,
            period_end=now,
        )
        assert {r.product for r in results} == {"voicewise", "hopwise"}
        assert out.exists()
        payload = json.loads(out.read_text())
        assert "voicewise" in payload["products"]
        assert "hopwise" in payload["products"]
        assert payload["products"]["voicewise"]["narrative"] == "Yes."
        # exactly one Claude call per product
        assert len(client.messages.calls) == 2

    def test_run_with_explicit_products(self, tmp_path):
        now = datetime.now(timezone.utc)
        _seed([
            {"product": "voicewise", "event_type": "voice.transcription",
             "timestamp": now - timedelta(hours=1), "session_id": "s1"},
        ])
        out = tmp_path / "insights.json"
        results = run(
            database_url=TEST_DB_URL,
            products=["voicewise"],
            output_path=out,
            anthropic_client=None,  # explicitly skip Claude
            period_end=now,
        )
        assert len(results) == 1
        assert results[0].product == "voicewise"
        assert out.exists()
