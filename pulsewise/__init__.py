"""PulseWise — AI-native event middleware client SDK.

This is the public, distributable surface. Consumers do:

    from pulsewise import PulseClient, EventType

    pulse = PulseClient(
        product="voicewise",
        collector_url=os.environ["PULSEWISE_URL"],
        async_mode=True,
        enabled=os.getenv("PULSEWISE_ENABLED", "true") == "true",
    )

The implementation lives in `sdk/python/pulsewise.py` (the SDK proper) and
`core/event_schema.py` (the canonical event schema). This package is a thin
shim that re-exports the public API so the import path is `pulsewise` rather
than `sdk.python.pulsewise`. The shim exists because the same repo ships both
a service (collector + summarizer + dashboard) and a client SDK; service code
keeps using its internal layout, while external consumers get a clean module.
"""
from sdk.python.pulsewise import (
    CircuitBreaker,
    CircuitState,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    PulseClient,
)
from core.event_schema import (
    EventType,
    PulseEvent,
    VALID_OUTCOMES,
    VALID_PRODUCTS,
    validate_event,
)

__all__ = [
    "PulseClient",
    "CircuitBreaker",
    "CircuitState",
    "EventType",
    "PulseEvent",
    "validate_event",
    "VALID_PRODUCTS",
    "VALID_OUTCOMES",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_COOLDOWN_SECONDS",
]

__version__ = "0.1.0"
