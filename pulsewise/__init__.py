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
    DEFAULT_VALID_PRODUCTS,
    EventType,
    PulseEvent,
    VALID_OUTCOMES,
    get_valid_products,
    validate_event,
)

__all__ = [
    "PulseClient",
    "CircuitBreaker",
    "CircuitState",
    "EventType",
    "PulseEvent",
    "validate_event",
    "get_valid_products",
    "DEFAULT_VALID_PRODUCTS",
    "VALID_PRODUCTS",
    "VALID_OUTCOMES",
    "DEFAULT_FAILURE_THRESHOLD",
    "DEFAULT_COOLDOWN_SECONDS",
]

def __getattr__(name: str):
    """Keep `VALID_PRODUCTS` live rather than snapshotting it at import time.

    The allowlist is read from PULSEWISE_VALID_PRODUCTS; binding it here would
    freeze whatever the environment held when the consumer first imported us.
    """
    if name == "VALID_PRODUCTS":
        return get_valid_products()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__version__ = "0.1.0"
