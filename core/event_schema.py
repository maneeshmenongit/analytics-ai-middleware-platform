"""Phase 1A — canonical PulseEvent schema.

Three layers per event: base, AI context, product payload.
This module is pure stdlib; the SDK and the collector both import from here.
"""
from __future__ import annotations

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

    CUSTOM = "custom"


VALID_PRODUCTS: set[str] = {"hopwise", "voicewise", "helmerwise", "scriptwise", "agentwise"}
VALID_OUTCOMES: set[str] = {"success", "failure", "ignored", "retry"}


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

    if event.product not in VALID_PRODUCTS:
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
