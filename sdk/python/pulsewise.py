"""Phase 1C — PulseWise Python SDK.

Lightweight client for emitting AI-native events. Designed for zero overhead in
the calling product:

- async_mode=True dispatches to a background thread; track() returns immediately
- enabled=False is a complete no-op (no event_id minting, no queueing)
- A circuit breaker (5 failures → OPEN for 60s) prevents repeated network attempts
  during a PulseWise outage, protecting consumer latency

PII contract: never pass raw email/name/phone to track(). user_id must be
hashed/anonymized by the caller before reaching this SDK.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import httpx

from core.event_schema import EventType, PulseEvent, validate_event

logger = logging.getLogger("pulsewise.sdk")


DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_BATCH_SIZE = 10
DEFAULT_FLUSH_INTERVAL_SECONDS = 1.0
DEFAULT_HTTP_TIMEOUT_SECONDS = 2.0


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        clock=time.monotonic,
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._lock = threading.Lock()

        self.state: CircuitState = CircuitState.CLOSED
        self.failure_count: int = 0
        self.opened_at: Optional[float] = None

    def record_success(self) -> None:
        with self._lock:
            self.failure_count = 0
            self.state = CircuitState.CLOSED
            self.opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = self._clock()

    def allow_request(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if self.opened_at is None:
                    return True
                if self._clock() - self.opened_at >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False
            return True


@dataclass
class _Job:
    payload: dict[str, Any]


_SHUTDOWN = object()


class PulseClient:
    def __init__(
        self,
        product: str,
        collector_url: Optional[str] = None,
        async_mode: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        flush_interval_seconds: float = DEFAULT_FLUSH_INTERVAL_SECONDS,
        enabled: bool = True,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.product = product
        self.collector_url = collector_url.rstrip("/") if collector_url else None
        self.async_mode = async_mode
        self.batch_size = max(1, batch_size)
        self.flush_interval_seconds = flush_interval_seconds
        self.enabled = enabled
        self.http_timeout_seconds = http_timeout_seconds

        self.circuit = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )

        self._client: Optional[httpx.Client] = None
        if enabled and collector_url:
            self._client = httpx.Client(
                timeout=http_timeout_seconds,
                transport=transport,
            )

        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stopped = threading.Event()

        if self.enabled and self.async_mode and self.collector_url:
            self._worker = threading.Thread(
                target=self._run_worker,
                name="pulsewise-sdk-worker",
                daemon=True,
            )
            self._worker.start()

    # ---------- public API ----------

    def track(
        self,
        event_type,
        session_id: str,
        outcome: str = "success",
        user_id: Optional[str] = None,
        model_name: Optional[str] = None,
        model_provider: Optional[str] = None,
        confidence: Optional[float] = None,
        latency_ms: Optional[int] = None,
        tokens_used: Optional[int] = None,
        cost_usd: Optional[float] = None,
        error_code: Optional[str] = None,
        retry_count: int = 0,
        context: Optional[dict[str, Any]] = None,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Emit an event. Returns True if accepted for delivery, False if dropped.

        Never raises. enabled=False is a hard no-op (no event_id minting either).
        """
        if not self.enabled:
            return False
        if not self.collector_url:
            return False

        if not self.circuit.allow_request():
            return False

        et = event_type.value if isinstance(event_type, EventType) else str(event_type)

        event = PulseEvent(
            product=self.product,
            event_type=et,
            session_id=session_id,
            outcome=outcome,
            user_id=user_id,
            model_name=model_name,
            model_provider=model_provider,
            confidence=confidence,
            latency_ms=latency_ms,
            tokens_used=tokens_used,
            cost_usd=cost_usd,
            error_code=error_code,
            retry_count=retry_count,
            context=context or {},
            tags=tags or [],
        )

        errors = validate_event(event)
        if errors:
            logger.warning("pulsewise: dropping invalid event: %s", "; ".join(errors))
            return False

        payload = event.to_dict()

        if self.async_mode:
            self._queue.put(_Job(payload=payload))
            return True

        return self._send_batch_sync([payload])

    def flush(self, timeout: Optional[float] = None) -> None:
        """Block until the worker has drained its queue. No-op in sync mode."""
        if not self.async_mode or self._worker is None:
            return
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self._queue.empty():
            if deadline is not None and time.monotonic() >= deadline:
                return
            time.sleep(0.01)

    def close(self) -> None:
        if self._stopped.is_set():
            return
        if self._worker is not None:
            self._queue.put(_SHUTDOWN)
            self._worker.join(timeout=5.0)
        self._stopped.set()
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    def __enter__(self) -> "PulseClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---------- internals ----------

    def _run_worker(self) -> None:
        buffer: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        shutting_down = False

        while True:
            timeout = max(0.01, self.flush_interval_seconds - (time.monotonic() - last_flush))
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None

            if item is _SHUTDOWN:
                shutting_down = True
                # drain any events queued before _SHUTDOWN
                while True:
                    try:
                        nxt = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if nxt is _SHUTDOWN:
                        continue
                    if isinstance(nxt, _Job):
                        buffer.append(nxt.payload)
                if buffer:
                    self._send_batch_sync(buffer)
                    buffer.clear()
                return

            if isinstance(item, _Job):
                buffer.append(item.payload)

            should_flush = (
                len(buffer) >= self.batch_size
                or (buffer and (time.monotonic() - last_flush) >= self.flush_interval_seconds)
            )
            if should_flush:
                self._send_batch_sync(buffer)
                buffer.clear()
                last_flush = time.monotonic()

            if shutting_down:
                return

    def _send_batch_sync(self, batch: list[dict[str, Any]]) -> bool:
        if not batch:
            return True
        if self._client is None or not self.collector_url:
            return False

        if not self.circuit.allow_request():
            return False

        url = f"{self.collector_url}/events"
        try:
            payload = batch[0] if len(batch) == 1 else batch
            resp = self._client.post(url, json=payload)
            if 200 <= resp.status_code < 300:
                self.circuit.record_success()
                return True
            self.circuit.record_failure()
            logger.warning("pulsewise: collector returned %s", resp.status_code)
            return False
        except Exception as exc:
            self.circuit.record_failure()
            logger.warning("pulsewise: send failed: %s", exc)
            return False
