"""New tests for m2: EventType.VIA_HINT / VIA_INSTRUMENT and the product-namespace
rule in validate_event(). See core/event_schema.py and scripts/check_m2_event_types.py.
"""
from __future__ import annotations

import os

import pytest

from core.event_schema import EventType, PulseEvent, validate_event


@pytest.fixture(autouse=True)
def _products(monkeypatch):
    monkeypatch.setenv("PULSEWISE_VALID_PRODUCTS", "voicewise,via")
    yield


def _errors(product: str, event_type: str) -> list[str]:
    return validate_event(PulseEvent(product=product, event_type=event_type, session_id="s"))


class TestNewViaMembers:
    def test_via_hint_value(self):
        assert EventType.VIA_HINT == "via.hint"
        assert EventType.VIA_HINT.value == "via.hint"

    def test_via_instrument_value(self):
        assert EventType.VIA_INSTRUMENT == "via.instrument"
        assert EventType.VIA_INSTRUMENT.value == "via.instrument"


class TestNamespaceAccepted:
    @pytest.mark.parametrize(
        "product,event_type",
        [
            ("voicewise", "voice.transcription"),
            ("via", "via.llm_call"),
            ("via", "via.hint"),
            ("via", "via.instrument"),
            ("via", "via.step_status"),
            ("via", "via.memory"),
            ("voicewise", "voicewise.custom_metric"),
            ("via", "custom"),
            ("voicewise", "via.llm_call"),
            ("via", "via." + "k" * 60),
        ],
    )
    def test_accepted(self, product, event_type):
        assert _errors(product, event_type) == []


class TestNamespaceRejected:
    @pytest.mark.parametrize(
        "product,event_type",
        [
            ("via", "foo"),
            ("via", "voicewise.x"),
            ("via", "via."),
            ("via", "via.Bad-Kind"),
            ("via", "via." + "k" * 61),
            ("via", "via.step status"),
        ],
    )
    def test_rejected_names_event_type(self, product, event_type):
        errs = _errors(product, event_type)
        assert errs, f"expected {event_type!r} to be rejected"
        assert any("event_type" in e for e in errs)
