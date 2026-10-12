"""Milestone m3 -- over-long fields are rejected per-event, naming the field,
never as a 503 for the whole batch.

Covers: validate_event rejects a value LONGER than its column (session_id 255,
user_id 64, model_name 64, model_provider 32, error_code 64, event_type 64),
accepts a value exactly AT the limit, and the error names the offending field
(e.g. "model_name"). Also covers the collector's existing per-event-rejection
flow: POST /events with [good, model_name too long, good] answers 200 with
accepted 2 / rejected 1, the one error at index 1 naming model_name, and both
good events persisted while the too-long one is not.
"""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from core.event_schema import PulseEvent, validate_event
from ingestion.collector import create_app
from ingestion.db import apply_migrations

TEST_DB_URL = os.getenv(
    "PULSEWISE_TEST_DATABASE_URL",
    "postgresql://maneeshmenon@localhost:5432/pulsewise_test",
)


def _pg_reachable(url: str) -> bool:
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=2):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(TEST_DB_URL), reason="postgres not reachable at PULSEWISE_TEST_DATABASE_URL"
)


def _ok_event(**overrides):
    base = dict(product="voicewise", event_type="voice.transcription", session_id="s")
    base.update(overrides)
    return PulseEvent(**base)


class TestLengthLimitsAccepted:
    def test_session_id_at_limit_accepted(self):
        ev = _ok_event(session_id="x" * 255)
        assert validate_event(ev) == []

    def test_user_id_at_limit_accepted(self):
        ev = _ok_event(user_id="x" * 64)
        assert validate_event(ev) == []

    def test_model_name_at_limit_accepted(self):
        ev = _ok_event(model_name="x" * 64)
        assert validate_event(ev) == []

    def test_model_provider_at_limit_accepted(self):
        ev = _ok_event(model_provider="x" * 32)
        assert validate_event(ev) == []

    def test_error_code_at_limit_accepted(self):
        ev = _ok_event(error_code="x" * 64)
        assert validate_event(ev) == []


class TestLengthLimitsRejected:
    def test_session_id_over_limit_rejected_naming_field(self):
        ev = _ok_event(session_id="x" * 256)
        errs = validate_event(ev)
        assert any("session_id" in e for e in errs)

    def test_user_id_over_limit_rejected_naming_field(self):
        ev = _ok_event(user_id="x" * 65)
        errs = validate_event(ev)
        assert any("user_id" in e for e in errs)

    def test_model_name_over_limit_rejected_naming_field(self):
        ev = _ok_event(model_name="x" * 65)
        errs = validate_event(ev)
        assert any("model_name" in e for e in errs)
        assert any("too long" in e for e in errs)

    def test_model_provider_over_limit_rejected_naming_field(self):
        ev = _ok_event(model_provider="x" * 33)
        errs = validate_event(ev)
        assert any("model_provider" in e for e in errs)

    def test_error_code_over_limit_rejected_naming_field(self):
        ev = _ok_event(error_code="x" * 65)
        errs = validate_event(ev)
        assert any("error_code" in e for e in errs)

    def test_event_type_over_limit_rejected_naming_field(self):
        ev = _ok_event(event_type="voice." + "t" * 59)  # 65 chars total
        errs = validate_event(ev)
        assert any("event_type" in e for e in errs)


@pytest.fixture
def app():
    apply_migrations(TEST_DB_URL)
    application = create_app(database_url=TEST_DB_URL, run_migrations=False)
    yield application
    application.state.pool.close()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


class TestCollectorPerEventRejection:
    def test_batch_with_long_model_name_partially_accepted(self, client, app):
        ids = [str(uuid.uuid4()) for _ in range(3)]
        base = {
            "product": "voicewise",
            "event_type": "voice.transcription",
            "session_id": "test-field-lengths",
        }
        batch = [
            dict(base, event_id=ids[0]),
            dict(base, event_id=ids[1], model_name="m" * 65),
            dict(base, event_id=ids[2]),
        ]
        try:
            resp = client.post("/events", json=batch)
            assert resp.status_code == 200
            body = resp.json()
            assert body["accepted"] == 2
            assert body["rejected"] == 1
            assert len(body["errors"]) == 1
            err = body["errors"][0]
            assert err["index"] == 1
            assert any("model_name" in e for e in err["errors"])

            import psycopg

            with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
                got = {
                    str(row[0])
                    for row in conn.execute(
                        "select event_id from pulse_events where event_id = any(%s)",
                        (ids,),
                    ).fetchall()
                }
            assert got == {ids[0], ids[2]}
        finally:
            import psycopg

            with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
                conn.execute("delete from pulse_events where event_id = any(%s)", (ids,))
