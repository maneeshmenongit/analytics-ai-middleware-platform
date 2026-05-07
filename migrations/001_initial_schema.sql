-- PulseWise Phase 1B — initial schema.
-- pulse_events: one row per emitted event from any consumer product.

CREATE TABLE IF NOT EXISTS pulse_events (
    event_id        UUID PRIMARY KEY,
    product         VARCHAR(32) NOT NULL,
    event_type      VARCHAR(64) NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    session_id      VARCHAR(64) NOT NULL,
    user_id         VARCHAR(64),
    model_name      VARCHAR(64),
    model_provider  VARCHAR(32),
    confidence      FLOAT,
    latency_ms      INTEGER,
    tokens_used     INTEGER,
    cost_usd        DECIMAL(12, 6),
    outcome         VARCHAR(16) NOT NULL,
    error_code      VARCHAR(64),
    retry_count     INTEGER NOT NULL DEFAULT 0,
    context         JSONB NOT NULL DEFAULT '{}'::jsonb,
    tags            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_product_timestamp ON pulse_events (product, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_event_type        ON pulse_events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_outcome           ON pulse_events (outcome);
CREATE INDEX IF NOT EXISTS idx_events_session           ON pulse_events (session_id);
