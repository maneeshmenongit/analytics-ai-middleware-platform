import os
import uuid
from datetime import datetime, timezone

import pytest

# Skip the entire module if Postgres isn't reachable for the test DB.
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
        f"Postgres test DB not reachable at {TEST_DB_URL}; "
        "create with `createdb pulsewise_test` or set PULSEWISE_TEST_DATABASE_URL.",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from ingestion.collector import create_app  # noqa: E402
from ingestion.db import apply_migrations  # noqa: E402


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    apply_migrations(TEST_DB_URL)
    # Point /insights/{product} at a tmp path so tests don't read the real
    # data/insights_summary.json from the dev environment.
    insights_dir = tmp_path_factory.mktemp("collector_insights")
    os.environ["PULSEWISE_INSIGHTS_PATH"] = str(insights_dir / "insights_summary.json")
    application = create_app(database_url=TEST_DB_URL, run_migrations=False)
    yield application
    os.environ.pop("PULSEWISE_INSIGHTS_PATH", None)


@pytest.fixture(autouse=True)
def _truncate(app):
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE pulse_events;")
    yield


@pytest.fixture(scope="module")
def client(app):
    with TestClient(app) as c:
        yield c


def _event(**overrides):
    base = {
        "event_id": str(uuid.uuid4()),
        "product": "voicewise",
        "event_type": "voice.transcription",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": "sess-1",
        "outcome": "success",
        "confidence": 0.9,
        "latency_ms": 120,
        "context": {"k": "v"},
        "tags": ["t1"],
    }
    base.update(overrides)
    return base


def _row_count(product: str = None) -> int:
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        with conn.cursor() as cur:
            if product:
                cur.execute("SELECT COUNT(*) FROM pulse_events WHERE product=%s;", (product,))
            else:
                cur.execute("SELECT COUNT(*) FROM pulse_events;")
            return cur.fetchone()[0]


# ---------- /health ----------

class TestHealth:
    def test_health_ok_when_db_reachable(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db"] is True


# ---------- POST /events ----------

class TestPostEventsSingle:
    def test_single_event_accepted_and_persisted(self, client):
        resp = client.post("/events", json=_event())
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 1
        assert body["rejected"] == 0
        assert _row_count("voicewise") == 1

    def test_persisted_fields_match(self, client):
        eid = str(uuid.uuid4())
        payload = _event(
            event_id=eid,
            confidence=0.42,
            latency_ms=999,
            cost_usd=0.0123,
            tags=["a", "b"],
            context={"nested": {"x": 1}},
        )
        client.post("/events", json=payload)
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT product, confidence, latency_ms, cost_usd, tags, context "
                    "FROM pulse_events WHERE event_id=%s;",
                    (eid,),
                )
                row = cur.fetchone()
        assert row is not None
        product, conf, lat, cost, tags, ctx = row
        assert product == "voicewise"
        assert conf == 0.42
        assert lat == 999
        assert float(cost) == 0.0123
        assert tags == ["a", "b"]
        assert ctx == {"nested": {"x": 1}}

    def test_idempotent_on_duplicate_event_id(self, client):
        ev = _event()
        r1 = client.post("/events", json=ev)
        r2 = client.post("/events", json=ev)
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["accepted"] == 1
        assert r2.json()["accepted"] == 0  # ON CONFLICT DO NOTHING
        assert _row_count() == 1


class TestPostEventsBatch:
    def test_batch_of_ten_accepted(self, client):
        events = [_event() for _ in range(10)]
        resp = client.post("/events", json=events)
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 10
        assert _row_count() == 10

    def test_batch_over_max_rejected(self, client):
        events = [_event() for _ in range(101)]
        resp = client.post("/events", json=events)
        assert resp.status_code == 422
        assert _row_count() == 0

    def test_batch_partial_validation_failure(self, client):
        events = [
            _event(),
            _event(product="not-a-product"),  # invalid product
            _event(),
        ]
        resp = client.post("/events", json=events)
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 2
        assert body["rejected"] == 1
        assert body["errors"][0]["index"] == 1
        assert any("product" in e.lower() for e in body["errors"][0]["errors"])
        assert _row_count() == 2

    def test_empty_batch_400(self, client):
        resp = client.post("/events", json=[])
        assert resp.status_code == 400


class TestPostEventsValidation:
    def test_invalid_outcome(self, client):
        resp = client.post("/events", json=_event(outcome="bogus"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["accepted"] == 0
        assert body["rejected"] == 1
        assert _row_count() == 0

    def test_confidence_out_of_range(self, client):
        resp = client.post("/events", json=_event(confidence=1.5))
        body = resp.json()
        assert body["rejected"] == 1
        assert _row_count() == 0

    def test_invalid_json_400(self, client):
        resp = client.post(
            "/events",
            content=b"{not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_top_level_string_400(self, client):
        resp = client.post("/events", json="hello")
        assert resp.status_code == 400


# ---------- GET /events/recent ----------

class TestRecent:
    def test_returns_events_in_descending_order(self, client):
        events = [
            _event(timestamp="2026-01-01T10:00:00+00:00"),
            _event(timestamp="2026-01-01T11:00:00+00:00"),
            _event(timestamp="2026-01-01T12:00:00+00:00"),
        ]
        client.post("/events", json=events)
        resp = client.get("/events/recent?limit=10")
        assert resp.status_code == 200
        rows = resp.json()["events"]
        assert len(rows) == 3
        timestamps = [r["timestamp"] for r in rows]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_filter_by_product(self, client):
        client.post("/events", json=[
            _event(product="voicewise"),
            _event(product="hopwise"),
            _event(product="hopwise"),
        ])
        resp = client.get("/events/recent?product=hopwise&limit=10")
        rows = resp.json()["events"]
        assert len(rows) == 2
        assert all(r["product"] == "hopwise" for r in rows)


# ---------- GET /insights/{product} ----------

class TestInsights:
    def test_no_file_returns_200_with_empty_payload(self, client):
        resp = client.get("/insights/voicewise")
        assert resp.status_code == 200
        body = resp.json()
        assert body["product"] == "voicewise"
        assert body["narrative"] is None
        assert body["recommendations"] == []

    def test_reads_insights_file_when_present(self, client):
        import json as _json
        from pathlib import Path as _Path
        path = _Path(os.environ["PULSEWISE_INSIGHTS_PATH"])
        path.write_text(_json.dumps({
            "generated_at": "2026-05-05T01:00:00+00:00",
            "products": {
                "voicewise": {
                    "product": "voicewise",
                    "narrative": "All systems nominal.",
                    "recommendations": ["Keep monitoring."],
                    "anomalies": [],
                    "total_events": 100,
                }
            },
        }))
        try:
            resp = client.get("/insights/voicewise")
            assert resp.status_code == 200
            body = resp.json()
            assert body["narrative"] == "All systems nominal."
            assert body["recommendations"] == ["Keep monitoring."]
            assert body["generated_at"] == "2026-05-05T01:00:00+00:00"
        finally:
            path.unlink()

    def test_unknown_product_returns_empty(self, client):
        import json as _json
        from pathlib import Path as _Path
        path = _Path(os.environ["PULSEWISE_INSIGHTS_PATH"])
        path.write_text(_json.dumps({
            "generated_at": "2026-05-05T01:00:00+00:00",
            "products": {"voicewise": {"narrative": "x", "recommendations": []}},
        }))
        try:
            resp = client.get("/insights/hopwise")
            assert resp.status_code == 200
            body = resp.json()
            assert body["narrative"] is None
            assert body["recommendations"] == []
        finally:
            path.unlink()
