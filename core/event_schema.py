"""Phase 1A — canonical PulseEvent schema.

Three layers per event: base, AI context, product payload.
This module is pure stdlib; the SDK and the collector both import from here.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    VOICE_TRANSCRIPTION = "voice.transcription"
    VOICE_SYNTHESIS = "voice.synthesis"
    VOICE_ROUTING_DECISION = "voice.routing_decision"
    VOICE_PROVIDER_FALLBACK = "voice.provider_fallback"

    RECOMMENDATION_SHOWN = "recommendation.shown"
    RECOMMENDATION_CLICKED = "recommendation.clicked"
    RECOMMENDATION_IGNORED = "recommendation.ignored"
    RECOMMENDATION_SAVED = "recommendation.saved"

    GENERATION_STARTED = "generation.started"
    GENERATION_COMPLETED = "generation.completed"
    GENERATION_RETRIED = "generation.retried"
    GENERATION_ABANDONED = "generation.abandoned"

    CONTENT_VIEWED = "content.viewed"
    CONTENT_REQUESTED = "content.requested"
    CONTENT_DECLINED = "content.declined"

    AGENT_TASK_STARTED = "agent.task_started"
    AGENT_TASK_COMPLETED = "agent.task_completed"
    AGENT_TASK_BLOCKED = "agent.task_blocked"

    # Via record types. Named for what they are so the rollups this integration
    # exists to serve (cost decomposition, hint provenance, inert-mechanism
    # detection) are queries against event_type, not string matching inside the
    # context JSONB blob.
    VIA_LLM_CALL = "via.llm_call"
    VIA_GATE = "via.gate"
    VIA_MILESTONE_STATUS = "via.milestone_status"
    VIA_STEP = "via.step"
    VIA_DELEGATION = "via.delegation"
    VIA_REVIEWER_GATE = "via.reviewer_gate"
    VIA_BROAD_SWEEP = "via.broad_sweep"

    CUSTOM = "custom"


# The five products PulseWise shipped with. This is the *default*, not the
# limit: the allowlist is read from the PULSEWISE_VALID_PRODUCTS env var so
# admitting a new client is a config change rather than an upstream code
# change. See get_valid_products().
DEFAULT_VALID_PRODUCTS: frozenset[str] = frozenset(
    {"hopwise", "voicewise", "helmerwise", "scriptwise", "agentwise"}
)

VALID_PRODUCTS_ENV_VAR = "PULSEWISE_VALID_PRODUCTS"

# Bounded by pulse_events.product VARCHAR(32) in migrations/001_initial_schema.sql.
# A name longer than this would be admitted here and then fail at INSERT, so it
# is rejected at config-load time instead.
MAX_PRODUCT_NAME_LENGTH = 32

VALID_OUTCOMES: set[str] = {"success", "failure", "ignored", "retry"}


def get_valid_products() -> frozenset[str]:
    """The product allowlist, from PULSEWISE_VALID_PRODUCTS if set.

    Format is a comma-separated list, e.g. "voicewise,hopwise,via". Entries are
    stripped and lowercased; blanks are ignored. An unset or all-blank value
    falls back to DEFAULT_VALID_PRODUCTS, so existing deployments that set
    nothing keep the exact Phase 1 behaviour.

    Read on every call rather than cached: tests and the collector may change
    the environment at runtime, and this is a set-membership check on a request
    path that already does network and database I/O.
    """
    raw = os.getenv(VALID_PRODUCTS_ENV_VAR)
    if raw is None:
        return DEFAULT_VALID_PRODUCTS

    names = {part.strip().lower() for part in raw.split(",")}
    names.discard("")
    if not names:
        return DEFAULT_VALID_PRODUCTS

    oversized = sorted(n for n in names if len(n) > MAX_PRODUCT_NAME_LENGTH)
    if oversized:
        raise ValueError(
            f"{VALID_PRODUCTS_ENV_VAR} contains name(s) longer than "
            f"{MAX_PRODUCT_NAME_LENGTH} characters: {', '.join(oversized)}"
        )
    return frozenset(names)


def __getattr__(name: str):
    """Module-level fallback so `VALID_PRODUCTS` stays a live, public name.

    It was a module constant in Phase 1 and is re-exported from `core` and
    `pulsewise`. Resolving it here keeps those imports working while making the
    value reflect the current environment rather than import-time state.
    """
    if name == "VALID_PRODUCTS":
        return get_valid_products()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _new_event_id() -> str:
    return str(uuid.uuid4())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PulseEvent:
    product: str
    event_type: str
    session_id: str
    outcome: str = "success"

    user_id: Optional[str] = None

    model_name: Optional[str] = None
    model_provider: Optional[str] = None
    confidence: Optional[float] = None
    latency_ms: Optional[int] = None
    tokens_used: Optional[int] = None
    cost_usd: Optional[float] = None

    error_code: Optional[str] = None
    retry_count: int = 0

    context: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    event_id: str = field(default_factory=_new_event_id)
    timestamp: datetime = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        ts = self.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        et = self.event_type.value if isinstance(self.event_type, EventType) else self.event_type
        return {
            "event_id": self.event_id,
            "product": self.product,
            "event_type": et,
            "timestamp": ts.isoformat(),
            "session_id": self.session_id,
            "user_id": self.user_id,
            "model_name": self.model_name,
            "model_provider": self.model_provider,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "cost_usd": self.cost_usd,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "retry_count": self.retry_count,
            "context": self.context,
            "tags": self.tags,
        }


def validate_event(event: PulseEvent) -> list[str]:
    """Returns list of validation error messages. Empty list = valid."""
    errors: list[str] = []

    if event.product not in get_valid_products():
        errors.append(f"Unknown product: {event.product}")

    if event.confidence is not None and not 0.0 <= event.confidence <= 1.0:
        errors.append("confidence must be 0.0-1.0")

    if event.outcome not in VALID_OUTCOMES:
        errors.append(f"Invalid outcome: {event.outcome}")

    if event.cost_usd is not None and event.cost_usd < 0:
        errors.append("cost_usd cannot be negative")

    if event.latency_ms is not None and event.latency_ms < 0:
        errors.append("latency_ms cannot be negative")

    if event.retry_count < 0:
        errors.append("retry_count cannot be negative")

    if not event.session_id:
        errors.append("session_id is required")

    if not event.event_type:
        errors.append("event_type is required")

    return errors
