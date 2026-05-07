from datetime import datetime, timezone

import pytest

from core.event_schema import (
    EventType,
    PulseEvent,
    VALID_OUTCOMES,
    VALID_PRODUCTS,
    validate_event,
)


def _ok_event(**overrides):
    base = dict(
        product="voicewise",
        event_type=EventType.VOICE_TRANSCRIPTION.value,
        session_id="sess-1",
        outcome="success",
    )
    base.update(overrides)
    return PulseEvent(**base)


class TestPulseEventConstruction:
    def test_minimum_fields_construct(self):
        e = _ok_event()
        assert e.product == "voicewise"
        assert e.session_id == "sess-1"
        assert e.outcome == "success"

    def test_event_id_auto_generated_and_unique(self):
        a = _ok_event()
        b = _ok_event()
        assert a.event_id and b.event_id
        assert a.event_id != b.event_id

    def test_timestamp_is_utc(self):
        e = _ok_event()
        assert e.timestamp.tzinfo is not None
        assert e.timestamp.utcoffset().total_seconds() == 0

    def test_default_collections_independent_per_instance(self):
        a = _ok_event()
        b = _ok_event()
        a.tags.append("x")
        a.context["k"] = 1
        assert b.tags == []
        assert b.context == {}


class TestEventType:
    def test_all_event_types_are_strings(self):
        for member in EventType:
            assert isinstance(member.value, str)
            assert "." in member.value or member is EventType.CUSTOM

    def test_event_type_known_values_present(self):
        names = {m.value for m in EventType}
        assert "voice.transcription" in names
        assert "recommendation.shown" in names
        assert "generation.started" in names
        assert "agent.task_started" in names
        assert "custom" in names


class TestValidate:
    def test_valid_event_returns_no_errors(self):
        assert validate_event(_ok_event()) == []

    def test_unknown_product_flagged(self):
        e = _ok_event(product="not-a-product")
        errs = validate_event(e)
        assert any("Unknown product" in s for s in errs)

    def test_invalid_outcome_flagged(self):
        e = _ok_event(outcome="bogus")
        errs = validate_event(e)
        assert any("Invalid outcome" in s for s in errs)

    def test_confidence_out_of_range(self):
        for bad in (-0.1, 1.5):
            errs = validate_event(_ok_event(confidence=bad))
            assert any("confidence" in s for s in errs)

    def test_confidence_zero_is_valid(self):
        # spec's `confidence or 0.5` would silently rewrite 0.0 — we accept 0.0
        assert validate_event(_ok_event(confidence=0.0)) == []

    def test_confidence_one_is_valid(self):
        assert validate_event(_ok_event(confidence=1.0)) == []

    def test_confidence_none_is_valid(self):
        assert validate_event(_ok_event(confidence=None)) == []

    def test_negative_cost_flagged(self):
        errs = validate_event(_ok_event(cost_usd=-0.01))
        assert any("cost_usd" in s for s in errs)

    def test_negative_latency_flagged(self):
        errs = validate_event(_ok_event(latency_ms=-1))
        assert any("latency_ms" in s for s in errs)

    def test_missing_session_id_flagged(self):
        errs = validate_event(_ok_event(session_id=""))
        assert any("session_id" in s for s in errs)

    def test_all_valid_products_accepted(self):
        for p in VALID_PRODUCTS:
            assert validate_event(_ok_event(product=p)) == []

    def test_all_valid_outcomes_accepted(self):
        for o in VALID_OUTCOMES:
            assert validate_event(_ok_event(outcome=o)) == []


class TestSerialization:
    def test_to_dict_iso_timestamp(self):
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        e = _ok_event(timestamp=ts)
        d = e.to_dict()
        assert d["timestamp"].startswith("2026-01-01T12:00:00")
        assert d["product"] == "voicewise"
        assert d["event_type"] == "voice.transcription"

    def test_to_dict_accepts_naive_timestamp(self):
        ts = datetime(2026, 1, 1, 12, 0, 0)
        e = _ok_event(timestamp=ts)
        d = e.to_dict()
        assert "+00:00" in d["timestamp"] or d["timestamp"].endswith("Z") or "T" in d["timestamp"]

    def test_to_dict_handles_event_type_enum(self):
        e = _ok_event(event_type=EventType.RECOMMENDATION_SHOWN)
        d = e.to_dict()
        assert d["event_type"] == "recommendation.shown"
