from .event_schema import (
    DEFAULT_VALID_PRODUCTS,
    EventType,
    PulseEvent,
    VALID_OUTCOMES,
    get_valid_products,
    validate_event,
)

__all__ = [
    "PulseEvent",
    "EventType",
    "validate_event",
    "get_valid_products",
    "DEFAULT_VALID_PRODUCTS",
    "VALID_PRODUCTS",
    "VALID_OUTCOMES",
]


def __getattr__(name: str):
    """`VALID_PRODUCTS` is env-dependent, so it must not be bound at import.

    A plain `from .event_schema import VALID_PRODUCTS` would snapshot the value
    when this package is first imported, which is exactly the hardcoding the
    configurable allowlist removes. Forwarding keeps it live.
    """
    if name == "VALID_PRODUCTS":
        return get_valid_products()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
