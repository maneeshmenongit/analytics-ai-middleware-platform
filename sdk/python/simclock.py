"""Phase 2 (m2) — the shared SDK sim-clock helper.

One time source per product: a test-only pretend 'now' behind two independent
locks, so a product can simulate timestamps in tests/arcade drivers without any
risk of that leaking into a production run.

Lock 1 (from_env): the env var PULSEWISE_SIM_CLOCK must be EXACTLY "1" to turn
simulation on. Anything else -- unset, "", "0", "true", "yes" -- means OFF.

Lock 2 (__init__ / from_env): enabled=True together with production=True is
always refused (SimClockRefused). enabled=False with production=True is fine:
a disabled clock simply never simulates, in production or anywhere else.

This module is a pure, standalone helper: it has zero import-time dependency on
ingestion/collector.py or sdk/python/pulsewise.py, and it never patches global
time (datetime.datetime, time.time, ...). It only computes and returns
datetimes to its caller; it holds no state between .now() calls beyond the two
constructor-time flags, and it never touches Postgres or the filesystem.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Union

ENV_FLAG = "PULSEWISE_SIM_CLOCK"

UTC = timezone.utc


class SimClockRefused(Exception):
    """Raised when a SimClock would be enabled under a production config."""


def _parse_pretend(value: Union[str, datetime]) -> datetime:
    """Parse a pretend 'now' into a tz-aware UTC datetime.

    Accepts a datetime (naive is read as UTC) or an ISO-8601 string (a
    trailing 'Z' means UTC; a naive ISO string is read as UTC). Raises
    ValueError on anything that cannot be read.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("pretend time string is empty")
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError(
            f"pretend must be a datetime or ISO-8601 string, got {type(value).__name__}"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class SimClock:
    """A single time source for a product: real time, or (in test-only
    configs) a caller-supplied pretend instant.

    SimClock(enabled, production) -- Lock 2: enabled=True with production=True
    is refused. Construct directly when you already know both flags, or via
    .from_env(production=...) to additionally apply Lock 1 (the env var).
    """

    def __init__(self, enabled: bool, production: bool):
        if enabled and production:
            raise SimClockRefused(
                "SimClock refused: enabled=True is not permitted when production=True"
            )
        self._enabled = bool(enabled)

    @classmethod
    def from_env(cls, production: bool) -> "SimClock":
        """Lock 1: enabled only when PULSEWISE_SIM_CLOCK is exactly '1'.

        Any other value -- unset, '', '0', 'true', 'yes' -- means OFF. If the
        flag is '1' and production=True, Lock 2 (in __init__) raises
        SimClockRefused.
        """
        import os

        enabled = os.environ.get(ENV_FLAG) == "1"
        return cls(enabled=enabled, production=production)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def now(self, pretend: Optional[Union[str, datetime]] = None) -> datetime:
        """The current instant, timezone-aware, in UTC.

        - disabled: always the real current UTC time; a pretend value, if
          given, is ignored.
        - enabled, pretend given: that instant, converted to UTC. An
          unreadable pretend raises ValueError.
        - enabled, no pretend: the real current UTC time.
        """
        if not self._enabled or pretend is None:
            return datetime.now(UTC)
        return _parse_pretend(pretend)

    def is_simulated(self, pretend: Optional[Union[str, datetime]] = None) -> bool:
        """True only when this clock is enabled AND a pretend value is given."""
        return self._enabled and pretend is not None

    def tags(self, pretend: Optional[Union[str, datetime]] = None) -> list:
        """['sim-clock'] when this call is simulated, otherwise []."""
        return ["sim-clock"] if self.is_simulated(pretend=pretend) else []
