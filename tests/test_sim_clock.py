"""Tests for sdk/python/simclock.py (m2-sim-clock).

SimClock is a standalone, stdlib-only time-source helper: no DB, no files, no
threads, no patching of global time. Nothing here needs cleanup beyond
restoring the one env var it reads.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from sdk.python.simclock import ENV_FLAG, SimClock, SimClockRefused

UTC = timezone.utc
PRETEND = datetime(2026, 5, 1, 13, 30, tzinfo=UTC)


def _close_to_now(t: datetime) -> bool:
    return abs((t - datetime.now(UTC)).total_seconds()) <= 5


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(ENV_FLAG, raising=False)
    yield


class TestConstructionLocks:
    def test_enabled_with_production_refused(self):
        with pytest.raises(SimClockRefused):
            SimClock(enabled=True, production=True)

    def test_disabled_with_production_is_fine(self):
        c = SimClock(enabled=False, production=True)
        assert c.enabled is False

    def test_enabled_without_production_is_fine(self):
        c = SimClock(enabled=True, production=False)
        assert c.enabled is True

    def test_disabled_without_production_is_fine(self):
        c = SimClock(enabled=False, production=False)
        assert c.enabled is False


class TestFromEnv:
    @pytest.mark.parametrize(
        "value,want",
        [
            (None, False),
            ("1", True),
            ("0", False),
            ("", False),
            ("true", False),
            ("yes", False),
            ("TRUE", False),
            (" 1", False),
        ],
    )
    def test_only_exact_one_enables(self, monkeypatch, value, want):
        if value is None:
            monkeypatch.delenv(ENV_FLAG, raising=False)
        else:
            monkeypatch.setenv(ENV_FLAG, value)
        assert SimClock.from_env(production=False).enabled is want

    def test_flag_one_with_production_refused(self, monkeypatch):
        monkeypatch.setenv(ENV_FLAG, "1")
        with pytest.raises(SimClockRefused):
            SimClock.from_env(production=True)

    def test_flag_unset_with_production_is_fine(self, monkeypatch):
        monkeypatch.delenv(ENV_FLAG, raising=False)
        c = SimClock.from_env(production=True)
        assert c.enabled is False


class TestDisabledClock:
    def test_now_ignores_pretend_returns_real_utc(self):
        c = SimClock(enabled=False, production=False)
        t = c.now(pretend=PRETEND)
        assert t.utcoffset() == timedelta(0)
        assert _close_to_now(t)

    def test_now_without_pretend_returns_real_utc(self):
        c = SimClock(enabled=False, production=False)
        t = c.now()
        assert t.utcoffset() == timedelta(0)
        assert _close_to_now(t)

    def test_is_simulated_always_false(self):
        c = SimClock(enabled=False, production=False)
        assert c.is_simulated(pretend=PRETEND) is False
        assert c.is_simulated() is False

    def test_tags_always_empty(self):
        c = SimClock(enabled=False, production=False)
        assert c.tags(pretend=PRETEND) == []
        assert c.tags() == []


class TestEnabledClock:
    def test_now_without_pretend_returns_real_utc(self):
        c = SimClock(enabled=True, production=False)
        t = c.now()
        assert t.utcoffset() == timedelta(0)
        assert _close_to_now(t)
        assert c.tags() == []
        assert c.is_simulated() is False

    def test_now_with_datetime_pretend(self):
        c = SimClock(enabled=True, production=False)
        assert c.now(pretend=PRETEND) == PRETEND

    def test_now_with_naive_datetime_pretend_is_utc(self):
        c = SimClock(enabled=True, production=False)
        t = c.now(pretend=datetime(2026, 5, 1, 13, 30))
        assert t == PRETEND
        assert t.utcoffset() == timedelta(0)

    def test_now_with_iso_z_string(self):
        c = SimClock(enabled=True, production=False)
        assert c.now(pretend="2026-05-01T13:30:00Z") == PRETEND

    def test_now_with_offset_string_converted_to_utc(self):
        c = SimClock(enabled=True, production=False)
        assert c.now(pretend="2026-05-01T09:30:00-04:00") == PRETEND

    def test_unreadable_pretend_raises_value_error(self):
        c = SimClock(enabled=True, production=False)
        with pytest.raises(ValueError):
            c.now(pretend="not a time")

    def test_is_simulated_true_only_with_pretend(self):
        c = SimClock(enabled=True, production=False)
        assert c.is_simulated(pretend=PRETEND) is True
        assert c.is_simulated() is False

    def test_tags_sim_clock_only_with_pretend(self):
        c = SimClock(enabled=True, production=False)
        assert c.tags(pretend=PRETEND) == ["sim-clock"]
        assert c.tags() == []


class TestNeverPatchesGlobalTime:
    def test_datetime_now_unaffected(self):
        before = datetime.now(UTC)
        c = SimClock(enabled=True, production=False)
        c.now(pretend=PRETEND)
        after = datetime.now(UTC)
        assert abs((after - before).total_seconds()) < 5
        # datetime.now still reflects the real clock, not the pretend instant
        assert abs((after - PRETEND).total_seconds()) > 1

    def test_time_time_unaffected(self):
        import time
        before = time.time()
        c = SimClock(enabled=True, production=False)
        c.now(pretend=PRETEND)
        after = time.time()
        assert after >= before
