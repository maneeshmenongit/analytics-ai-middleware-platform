"""Admission of Via as a PulseWise client.

Covers the three changes from the Via change request:
  1. the product allowlist is configurable, not hardcoded
  2. EventType carries Via's record types
  3. the OTel GenAI convention version is pinned and recorded

The point of (1) is that the *next* client is a config change, so these tests
assert the mechanism with arbitrary names, not just with "via".
"""
import importlib

import pytest

import core
import core.event_schema as schema
from core.event_schema import (
    DEFAULT_VALID_PRODUCTS,
    MAX_PRODUCT_NAME_LENGTH,
    VALID_PRODUCTS_ENV_VAR,
    EventType,
    PulseEvent,
    get_valid_products,
    validate_event,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from an unset allowlist var."""
    monkeypatch.delenv(VALID_PRODUCTS_ENV_VAR, raising=False)
    yield


def _event(**overrides):
    base = dict(
        product="via",
        event_type=EventType.VIA_LLM_CALL.value,
        session_id="sess-via-1",
        outcome="success",
    )
    base.update(overrides)
    return PulseEvent(**base)


class TestAllowlistIsConfigurable:
    def test_default_is_the_original_five(self):
        assert get_valid_products() == {
            "hopwise", "voicewise", "helmerwise", "scriptwise", "agentwise",
        }

    def test_unset_env_preserves_phase_1_behaviour(self):
        # The regression that matters: existing deployments set nothing.
        assert validate_event(_event(product="voicewise")) == []
        assert any(
            "Unknown product" in e for e in validate_event(_event(product="via"))
        )

    def test_env_var_admits_a_new_product(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "voicewise,via")
        assert validate_event(_event(product="via")) == []

    def test_env_var_replaces_rather_than_extends(self, monkeypatch):
        # Setting the var is the full allowlist — an operator who lists only
        # "via" has deliberately excluded the rest.
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        assert get_valid_products() == {"via"}
        assert any(
            "Unknown product" in e
            for e in validate_event(_event(product="voicewise"))
        )

    def test_seventh_client_needs_no_code_change(self, monkeypatch):
        # The actual requirement: a name nobody wrote into the source.
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "honedwise,quartzwise")
        assert validate_event(_event(product="quartzwise")) == []

    def test_whitespace_and_case_are_normalised(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "  VIA , Voicewise  ")
        assert get_valid_products() == {"via", "voicewise"}

    def test_blank_entries_ignored(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via,,voicewise,")
        assert get_valid_products() == {"via", "voicewise"}

    def test_all_blank_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "  , ,")
        assert get_valid_products() == DEFAULT_VALID_PRODUCTS

    def test_empty_string_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "")
        assert get_valid_products() == DEFAULT_VALID_PRODUCTS

    def test_name_longer_than_db_column_is_rejected(self, monkeypatch):
        # pulse_events.product is VARCHAR(32); admitting a longer name here
        # would only fail later at INSERT.
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "v" * (MAX_PRODUCT_NAME_LENGTH + 1))
        with pytest.raises(ValueError, match="longer than"):
            get_valid_products()

    def test_name_exactly_at_limit_is_allowed(self, monkeypatch):
        name = "v" * MAX_PRODUCT_NAME_LENGTH
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, name)
        assert get_valid_products() == {name}

    def test_default_allowlist_is_immutable(self):
        # A caller mutating the returned set must not poison later validation.
        with pytest.raises(AttributeError):
            get_valid_products().add("via")  # type: ignore[attr-defined]


class TestAllowlistStaysLiveAcrossReexports:
    """VALID_PRODUCTS is public API; it must not be frozen at import time."""

    def test_schema_module_attribute_is_live(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        assert schema.VALID_PRODUCTS == {"via"}

    def test_core_reexport_is_live(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        assert core.VALID_PRODUCTS == {"via"}

    def test_pulsewise_shim_reexport_is_live(self, monkeypatch):
        pulsewise = importlib.import_module("pulsewise")
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        assert pulsewise.VALID_PRODUCTS == {"via"}

    def test_unknown_attribute_still_raises(self):
        with pytest.raises(AttributeError):
            schema.NOT_A_REAL_NAME

    def test_valid_products_still_exported(self):
        assert "VALID_PRODUCTS" in core.__all__
        pulsewise = importlib.import_module("pulsewise")
        assert "VALID_PRODUCTS" in pulsewise.__all__


class TestViaEventTypes:
    EXPECTED = {
        "via.llm_call",
        "via.gate",
        "via.milestone_status",
        "via.step",
        "via.delegation",
        "via.reviewer_gate",
        "via.broad_sweep",
    }

    def test_all_via_record_types_present(self):
        assert self.EXPECTED <= {m.value for m in EventType}

    def test_via_types_are_not_custom(self):
        # The whole point: these must not collapse into CUSTOM.
        for member in EventType:
            if member.value in self.EXPECTED:
                assert member is not EventType.CUSTOM

    def test_via_event_validates_when_admitted(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        for value in self.EXPECTED:
            assert validate_event(_event(event_type=value)) == []

    def test_via_types_fit_event_type_column(self):
        # pulse_events.event_type is VARCHAR(64).
        for value in self.EXPECTED:
            assert len(value) <= 64

    def test_enum_serialises_through_to_dict(self):
        d = _event(event_type=EventType.VIA_MILESTONE_STATUS).to_dict()
        assert d["event_type"] == "via.milestone_status"

    def test_existing_event_types_untouched(self):
        names = {m.value for m in EventType}
        for value in (
            "voice.transcription", "recommendation.shown",
            "generation.started", "content.viewed",
            "agent.task_started", "custom",
        ):
            assert value in names


class TestOtelPin:
    def test_version_is_pinned_and_recorded(self):
        from core.otel_genai import OTEL_SEMCONV_SOURCE, OTEL_SEMCONV_VERSION

        assert OTEL_SEMCONV_VERSION == "1.41.1"
        assert "v1.41.1" in OTEL_SEMCONV_SOURCE

    def test_attribute_names_via_requires_are_defined(self):
        from core import otel_genai

        for name in (
            "gen_ai.request.model",
            "gen_ai.usage.input_tokens",
            "gen_ai.usage.output_tokens",
            "gen_ai.provider.name",
        ):
            assert name in otel_genai.GEN_AI_ATTRIBUTES

    def test_all_attributes_use_gen_ai_prefix(self):
        from core import otel_genai

        assert all(a.startswith("gen_ai.") for a in otel_genai.GEN_AI_ATTRIBUTES)

    def test_module_carries_no_otel_dependency(self):
        # PulseWise adopts the names, not the SDK.
        import pathlib

        src = pathlib.Path("core/otel_genai.py").read_text()
        assert "import opentelemetry" not in src


class TestViaTrafficShape:
    """Via's real records must validate as described in the change request."""

    def test_llm_call_with_cost_and_tokens(self, monkeypatch):
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        from core.otel_genai import (
            GEN_AI_PROVIDER_NAME,
            GEN_AI_REQUEST_MODEL,
            GEN_AI_USAGE_INPUT_TOKENS,
        )

        e = _event(
            event_type=EventType.VIA_LLM_CALL.value,
            model_name="claude-opus-5",
            cost_usd=0.0421,
            tokens_used=1830,
            latency_ms=2210,
            context={
                "seat": "builder",
                "rung": 3,
                GEN_AI_REQUEST_MODEL: "claude-opus-5",
                GEN_AI_PROVIDER_NAME: "anthropic",
                GEN_AI_USAGE_INPUT_TOKENS: 1200,
            },
        )
        assert validate_event(e) == []

    def test_deterministic_record_carries_no_ai_context(self, monkeypatch):
        # Via's gate/milestone records are deterministic writes, zero LLM calls.
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via")
        e = _event(event_type=EventType.VIA_GATE.value, outcome="failure")
        assert validate_event(e) == []

    def test_honedwise_plan_events_admitted_alongside(self, monkeypatch):
        # The join of the two emitters is the stated value of the integration.
        monkeypatch.setenv(VALID_PRODUCTS_ENV_VAR, "via,honedwise")
        assert validate_event(_event(product="honedwise")) == []
        assert validate_event(_event(product="via")) == []
