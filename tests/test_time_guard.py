"""m3 — the unmarked-event time guard on POST /events.

An unmarked event's timestamp must be close to when it arrives. Outside the
window [received - 7 days, received + 5 minutes] it is still ACCEPTED, but
stored with timestamp = received, tagged "timestamp-clamped", with its
original time recorded in context["pulsewise.original_timestamp"]. Events
tagged source:synthetic or via-source:backfill are exempt and stored with the
time they sent, whatever it is.

Uses TEST_DB_URL exactly as tests/test_collector.py does, and cleans up every
row it inserts (by event_id) regardless of how the test ends.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

from ingestion.collector import create_app
from ingestion.db import apply_migrations

TEST_DB_URL = os.getenv(
    "PULSEWISE_TEST_DATABASE_URL",
    "postgresql://maneeshmenon@localhost:5432/pulsewise_test",
)

CLAMP_TAG = "timestamp-clamped"
ORIGINAL_KEY = "pulsewise.original_timestamp"


def _pg_reachable(url: str) -> bool:
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            conn.execute("SELECT 1;")
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(TEST_DB_URL), reason="Postgres test DB not reachable"
)


@pytest.fixture
def app():
    apply_migrations(TEST_DB_URL)
    application = create_app(database_url=TEST_DB_URL, run_migrations=False)
    yield application
    application.state.pool.close()


@pytest.fixture
def client(app):
    return TestClient(app)


def _event(event_id, ts, tags=None, context=None):
    payload = {
        "event_id": event_id,
        "product": "voicewise",
        "event_type": "voice.transcription",
        "session_id": "s-time-guard",
        "tags": list(tags or []),
        "context": context or {"k": "v"},
    }
    if ts is not None:
        payload["timestamp"] = ts.isoformat() if isinstance(ts, datetime) else ts
    return payload


def _fetch(event_id):
    with psycopg.connect(TEST_DB_URL) as conn:
        return conn.execute(
            "SELECT timestamp, tags, context FROM pulse_events WHERE event_id = %s",
            (event_id,),
        ).fetchone()


def _delete(event_ids):
    if not event_ids:
        return
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute(
            "DELETE FROM pulse_events WHERE event_id = ANY(%s)",
            (list(event_ids),),
        )


class TestTimeGuardClamping:
    def test_far_future_unmarked_event_is_clamped(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            now = datetime.now(timezone.utc)
            sent = now + timedelta(hours=1)
            resp = client.post(
                "/events", json=_event(event_id, sent, context={"k": "v"})
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["accepted"] == 1
            assert body["rejected"] == 0
            assert body["errors"] == []

            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG in stored_tags
            assert ctx.get("k") == "v"
            assert ctx.get(ORIGINAL_KEY) is not None
            parsed_original = datetime.fromisoformat(
                str(ctx[ORIGINAL_KEY]).replace("Z", "+00:00")
            )
            if parsed_original.tzinfo is None:
                parsed_original = parsed_original.replace(tzinfo=timezone.utc)
            assert abs((parsed_original - sent).total_seconds()) < 1
            # stored at receive time, not the sent time
            assert abs((stored_ts - now).total_seconds()) < 10
        finally:
            _delete(ids)

    def test_far_past_unmarked_event_is_clamped(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            now = datetime.now(timezone.utc)
            sent = now - timedelta(days=8)
            resp = client.post("/events", json=_event(event_id, sent))
            assert resp.status_code == 200
            body = resp.json()
            assert body["accepted"] == 1
            assert body["rejected"] == 0

            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG in stored_tags
            assert abs((stored_ts - now).total_seconds()) < 10
            assert ctx.get(ORIGINAL_KEY) is not None
        finally:
            _delete(ids)

    def test_in_window_event_is_not_clamped(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            now = datetime.now(timezone.utc)
            sent = now - timedelta(days=2)
            resp = client.post("/events", json=_event(event_id, sent))
            assert resp.status_code == 200
            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG not in stored_tags
            assert ORIGINAL_KEY not in ctx
            assert abs((stored_ts - sent).total_seconds()) < 1
        finally:
            _delete(ids)

    def test_synthetic_tag_exempts_far_past_event(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            sent = datetime.now(timezone.utc) - timedelta(days=90)
            resp = client.post(
                "/events", json=_event(event_id, sent, tags=["source:synthetic"])
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["accepted"] == 1

            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG not in stored_tags
            assert "source:synthetic" in stored_tags
            assert ORIGINAL_KEY not in ctx
            assert abs((stored_ts - sent).total_seconds()) < 1
        finally:
            _delete(ids)

    def test_backfill_tag_exempts_far_past_event(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            sent = datetime.now(timezone.utc) - timedelta(days=200)
            resp = client.post(
                "/events", json=_event(event_id, sent, tags=["via-source:backfill"])
            )
            assert resp.status_code == 200
            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG not in stored_tags
            assert abs((stored_ts - sent).total_seconds()) < 1
        finally:
            _delete(ids)

    def test_no_timestamp_is_stored_at_now_not_clamped(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            resp = client.post("/events", json=_event(event_id, None))
            assert resp.status_code == 200
            now = datetime.now(timezone.utc)
            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG not in stored_tags
            assert ORIGINAL_KEY not in ctx
            assert abs((stored_ts - now).total_seconds()) < 10
        finally:
            _delete(ids)

    def test_naive_timestamp_in_window_stored_as_is(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            sent_naive = (datetime.now(timezone.utc) - timedelta(days=2)).replace(
                tzinfo=None
            )
            resp = client.post(
                "/events", json=_event(event_id, sent_naive.isoformat())
            )
            assert resp.status_code == 200
            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, _ctx = row
            assert CLAMP_TAG not in stored_tags
            # stored as Postgres reads a naive instant today: unaffected by
            # the guard, whatever tz that resolves to.
            assert stored_ts is not None
        finally:
            _delete(ids)

    def test_naive_timestamp_out_of_window_is_clamped(self, client):
        event_id = str(uuid.uuid4())
        ids = [event_id]
        try:
            sent_naive = (datetime.now(timezone.utc) - timedelta(days=8)).replace(
                tzinfo=None
            )
            resp = client.post(
                "/events", json=_event(event_id, sent_naive.isoformat())
            )
            assert resp.status_code == 200
            now = datetime.now(timezone.utc)
            row = _fetch(event_id)
            assert row is not None
            stored_ts, stored_tags, ctx = row
            assert CLAMP_TAG in stored_tags
            assert ORIGINAL_KEY in ctx
            assert abs((stored_ts - now).total_seconds()) < 10
        finally:
            _delete(ids)

    def test_batch_clamped_event_counts_as_accepted_not_rejected(self, client):
        event_id = str(uuid.uuid4())
        other_id = str(uuid.uuid4())
        ids = [event_id, other_id]
        try:
            future = datetime.now(timezone.utc) + timedelta(days=1)
            ok_time = datetime.now(timezone.utc)
            resp = client.post(
                "/events",
                json=[
                    _event(event_id, future),
                    _event(other_id, ok_time),
                ],
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["accepted"] == 2
            assert body["rejected"] == 0
            assert body["errors"] == []
        finally:
            _delete(ids)
