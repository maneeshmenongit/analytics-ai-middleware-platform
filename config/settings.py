"""Env-backed config. Loads .env once, exposes a typed Settings dataclass."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from core.event_schema import get_valid_products

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: Optional[str]
    database_url: Optional[str]
    redis_url: Optional[str]

    pulsewise_port: int
    pulsewise_env: str

    aggregation_interval_minutes: int
    aggregation_lookback_hours: int

    pulsewise_url: Optional[str]
    pulsewise_enabled: bool

    circuit_failure_threshold: int
    circuit_cooldown_seconds: int

    # Ingestion admission allowlist. Resolved by core.event_schema so the SDK —
    # which ships without this module — reads the same value from the same env
    # var. Exposed here so service config has one place to look.
    valid_products: frozenset[str]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        database_url=os.getenv("DATABASE_URL"),
        redis_url=os.getenv("REDIS_URL"),
        pulsewise_port=_get_int("PULSEWISE_PORT", 8400),
        pulsewise_env=os.getenv("PULSEWISE_ENV", "development"),
        aggregation_interval_minutes=_get_int("AGGREGATION_INTERVAL_MINUTES", 60),
        aggregation_lookback_hours=_get_int("AGGREGATION_LOOKBACK_HOURS", 24),
        pulsewise_url=os.getenv("PULSEWISE_URL"),
        pulsewise_enabled=_get_bool("PULSEWISE_ENABLED", True),
        circuit_failure_threshold=_get_int("PULSEWISE_CIRCUIT_FAILURE_THRESHOLD", 5),
        circuit_cooldown_seconds=_get_int("PULSEWISE_CIRCUIT_COOLDOWN_SECONDS", 60),
        valid_products=get_valid_products(),
    )
