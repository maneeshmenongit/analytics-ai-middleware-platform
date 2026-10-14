"""New tests for m1-sdk-event-id-and-time: track()'s event_id/timestamp params
and validate_event()'s event_id / non-string field rejections.

Uses an in-process httpx.MockTransport so no real network or collector process
is needed, matching the pattern in tests/test_sdk.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from core.event_schema import PulseEvent, validate_event
from sdk.python.pulsewise import PulseClient

UTC = timezone.utc


def _client(sent: list):
    def handler(request):
        import json

        body = json.loads(request.content)
        sent.extend(body if isinstance(body, list) else [body])
        return httpx.Response(200, json={"accepted": 1, "rejected": 0, "errors": []})

    return PulseClient(
        product="voicewise",
        collector_url="http://pulsewise.test",
        async_mode=False,
        transport=httpx.MockTransport(handler),
    )


class TestTrackEventId:
    def test_event_id_sent_exactly_as_given(self):
        sent: list = []
        c = _client(sent)
        eid = str(uuid.uuid4())
        ok = c.track("voice.transcription", session_id="s1", event_id=eid)
        c.close()
        assert ok is True
        assert sent[0]["event_id"] == eid

    def test_invalid_event_id_drops_event(self):
        sent: list = []
        c = _client(sent)
        ok = c.track("voice.transcription", session_id="s1", event_id="not-a-uuid")
        c.close()
        assert ok is False
        assert sent == []

    def test_default_event_id_is_fresh_uuid(self):
        sent: list = []
        c = _client(sent)
        c.track("voice.transcription", session_id="s1")
        c.track("voice.transcription", session_id="s1")
        c.close()
        assert len(sent) == 2
        ids = [s["event_id"] for s in sent]
        for i in ids:
            uuid.UUID(i)
        assert ids[0] != ids[1]


class TestTrackTimestamp:
    def test_aware_datetime_timestamp_sent_as_given(self):
        sent: list = []
        c = _client(sent)
        when = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
        ok = c.track("voice.transcription", session_id="s1", timestamp=when)
        c.close()
        assert ok is True
        sent_dt = datetime.fromisoformat(sent[0]["timestamp"])
        assert sent_dt == when

    def test_naive_datetime_read_as_utc(self):
        sent: list = []
        c = _client(sent)
        when = datetime(2026, 9, 30, 12, 0)
        c.track("voice.transcription", session_id="s1", timestamp=when)
        c.close()
        sent_dt = datetime.fromisoformat(sent[0]["timestamp"])
        assert sent_dt == when.replace(tzinfo=UTC)

    def test_iso_string_with_trailing_z(self):
        sent: list = []
        c = _client(sent)
        c.track("voice.transcription", session_id="s1", timestamp="2026-09-30T12:00:00Z")
        c.close()
        sent_dt = datetime.fromisoformat(sent[0]["timestamp"])
        assert sent_dt == datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

    def test_unparseable_timestamp_drops_event_without_raising(self):
        sent: list = []
        c = _client(sent)
        result = c.track("voice.transcription", session_id="s1", timestamp="yesterday")
        c.close()
        assert result is False
        assert sent == []

    def test_default_timestamp_is_now_utc(self):
        sent: list = []
        c = _client(sent)
        before = datetime.now(UTC)
        c.track("voice.transcription", session_id="s1")
        c.close()
        sent_dt = datetime.fromisoformat(sent[0]["timestamp"])
        assert abs((sent_dt - before).total_seconds()) < 5


class TestValidateEventIdAndTypes:
    def test_bad_event_id_rejected_naming_field(self):
        ev = PulseEvent(
            product="voicewise",
            event_type="voice.transcription",
            session_id="s",
            event_id="not-a-uuid",
        )
        errors = validate_event(ev)
        assert any("event_id" in e for e in errors)

    def test_uppercase_uuid_event_id_accepted(self):
        ev = PulseEvent(
            product="voicewise",
            event_type="voice.transcription",
            session_id="s",
            event_id=str(uuid.uuid4()).upper(),
        )
        assert validate_event(ev) == []

    @pytest.mark.parametrize("field,value", [("user_id", 7), ("model_name", 3.5)])
    def test_non_string_length_checked_field_rejected_naming_field(self, field, value):
        ev = PulseEvent(
            product="voicewise",
            event_type="voice.transcription",
            session_id="s",
            **{field: value},
        )
        errors = validate_event(ev)
        assert any(field in e for e in errors)
