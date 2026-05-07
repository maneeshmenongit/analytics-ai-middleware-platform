import threading
import time

import httpx
import pytest

from core.event_schema import EventType
from sdk.python.pulsewise import (
    CircuitBreaker,
    CircuitState,
    PulseClient,
)


# ---------- helpers ----------

class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


class CountingTransport(httpx.BaseTransport):
    """In-process transport that counts requests and replays scripted responses."""

    def __init__(self, responses=None, default_status=200):
        self.responses = list(responses or [])
        self.default_status = default_status
        self.requests = []
        self.lock = threading.Lock()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.requests.append(request)
            if self.responses:
                spec = self.responses.pop(0)
            else:
                spec = self.default_status

        if isinstance(spec, Exception):
            raise spec
        if isinstance(spec, tuple):
            status, body = spec
        else:
            status, body = spec, b'{"accepted":1}'
        return httpx.Response(status, content=body)


# ---------- CircuitBreaker ----------

class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_open_state_blocks_requests_during_cooldown(self):
        clock = FakeClock()
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60, clock=clock)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False
        clock.advance(30)
        assert cb.allow_request() is False

    def test_transitions_to_half_open_after_cooldown(self):
        clock = FakeClock()
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60, clock=clock)
        cb.record_failure()
        cb.record_failure()
        clock.advance(60)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_success_in_half_open_closes_circuit(self):
        clock = FakeClock()
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60, clock=clock)
        cb.record_failure()
        cb.record_failure()
        clock.advance(60)
        cb.allow_request()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_success_resets_failure_counter(self):
        cb = CircuitBreaker(failure_threshold=5)
        for _ in range(3):
            cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED


# ---------- PulseClient: no-op / disabled ----------

class TestDisabledClient:
    def test_disabled_track_returns_false_no_network(self):
        t = CountingTransport()
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            enabled=False,
            transport=t,
        )
        result = c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        assert result is False
        assert len(t.requests) == 0
        c.close()

    def test_disabled_track_is_fast(self):
        c = PulseClient(product="voicewise", collector_url="http://stub", enabled=False)
        start = time.monotonic()
        for _ in range(1000):
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        elapsed = time.monotonic() - start
        assert elapsed < 0.5
        c.close()

    def test_no_collector_url_is_drop(self):
        c = PulseClient(product="voicewise", collector_url=None, enabled=True)
        assert c.track(EventType.VOICE_TRANSCRIPTION, session_id="s") is False
        c.close()


# ---------- PulseClient: sync mode round-trip ----------

class TestSyncClient:
    def test_successful_post_in_sync_mode(self):
        t = CountingTransport(default_status=200)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        ok = c.track(
            EventType.VOICE_TRANSCRIPTION,
            session_id="s",
            confidence=0.9,
            latency_ms=100,
        )
        assert ok is True
        assert len(t.requests) == 1
        assert "/events" in str(t.requests[0].url)
        c.close()

    def test_invalid_event_dropped_no_network(self):
        t = CountingTransport()
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        ok = c.track(EventType.VOICE_TRANSCRIPTION, session_id="s", outcome="bogus")
        assert ok is False
        assert len(t.requests) == 0
        c.close()

    def test_failure_does_not_raise(self):
        t = CountingTransport(responses=[(500, b"oops")])
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        ok = c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        assert ok is False
        c.close()

    def test_network_exception_does_not_raise(self):
        t = CountingTransport(responses=[httpx.ConnectError("boom")])
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        ok = c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        assert ok is False
        c.close()


# ---------- PulseClient: circuit integration ----------

class TestCircuitIntegration:
    def test_circuit_opens_after_5_failures_via_client(self):
        t = CountingTransport(default_status=500)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        for _ in range(5):
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        assert c.circuit.state == CircuitState.OPEN
        c.close()

    def test_open_circuit_drops_with_zero_network(self):
        t = CountingTransport(default_status=500)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        for _ in range(5):
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        before = len(t.requests)
        for _ in range(10):
            ok = c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
            assert ok is False
        assert len(t.requests) == before  # no new attempts
        c.close()

    def test_open_circuit_track_is_under_1ms(self):
        t = CountingTransport(default_status=500)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=t,
        )
        for _ in range(5):
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        assert c.circuit.state == CircuitState.OPEN

        durations = []
        for _ in range(200):
            t0 = time.perf_counter()
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
            durations.append(time.perf_counter() - t0)
        durations.sort()
        median = durations[len(durations) // 2]
        # Generous bound; expect ~µs but allow CI noise
        assert median < 0.001, f"median dropped-track latency {median*1000:.3f}ms exceeds 1ms"
        c.close()


# ---------- PulseClient: async batch flush ----------

class TestAsyncBatching:
    def test_async_track_returns_immediately(self):
        t = CountingTransport(default_status=200)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=True,
            batch_size=10,
            flush_interval_seconds=0.05,
            transport=t,
        )
        try:
            t0 = time.perf_counter()
            for _ in range(100):
                c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
            elapsed = time.perf_counter() - t0
            assert elapsed < 0.1, f"async track loop too slow: {elapsed:.3f}s"
        finally:
            c.close()

    def test_async_batch_flushes_at_size_threshold(self):
        t = CountingTransport(default_status=200)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=True,
            batch_size=5,
            flush_interval_seconds=10.0,  # long, force size-trigger
            transport=t,
        )
        try:
            for _ in range(5):
                c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and len(t.requests) == 0:
                time.sleep(0.02)
            assert len(t.requests) >= 1
        finally:
            c.close()

    def test_async_flushes_on_interval(self):
        t = CountingTransport(default_status=200)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=True,
            batch_size=100,  # high — must rely on interval flush
            flush_interval_seconds=0.1,
            transport=t,
        )
        try:
            for _ in range(3):
                c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and len(t.requests) == 0:
                time.sleep(0.02)
            assert len(t.requests) >= 1
        finally:
            c.close()

    def test_close_drains_pending_events(self):
        t = CountingTransport(default_status=200)
        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=True,
            batch_size=100,
            flush_interval_seconds=10.0,
            transport=t,
        )
        for _ in range(3):
            c.track(EventType.VOICE_TRANSCRIPTION, session_id="s")
        c.close()
        assert len(t.requests) >= 1


# ---------- payload shape ----------

class TestPayload:
    def test_payload_contains_required_fields(self):
        captured = {}

        class CaptureTransport(httpx.BaseTransport):
            def handle_request(self, request):
                import json as _json
                captured["body"] = _json.loads(request.content.decode())
                return httpx.Response(200, content=b'{"accepted":1}')

        c = PulseClient(
            product="voicewise",
            collector_url="http://stub",
            async_mode=False,
            transport=CaptureTransport(),
        )
        c.track(
            EventType.VOICE_ROUTING_DECISION,
            session_id="sess-99",
            user_id="hashed-abc",
            confidence=0.87,
            latency_ms=312,
            cost_usd=0.0021,
            context={"providers": ["deepgram", "whisper"]},
            tags=["fallback"],
        )
        body = captured["body"]
        assert body["product"] == "voicewise"
        assert body["event_type"] == "voice.routing_decision"
        assert body["session_id"] == "sess-99"
        assert body["user_id"] == "hashed-abc"
        assert body["confidence"] == 0.87
        assert body["latency_ms"] == 312
        assert body["context"]["providers"] == ["deepgram", "whisper"]
        assert "event_id" in body and body["event_id"]
        assert "timestamp" in body and body["timestamp"]
        c.close()
