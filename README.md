# PulseWise

AI-native event middleware. PulseWise captures events with intent context, AI
context, and product context — not just raw actions — so AI-powered products
have a proper feedback loop into model and product decisions.

This repository contains both the **service** (collector + aggregation summarizer
+ internal dashboard) and the **client SDK**. The SDK is what consumer products
(VoiceWise, Hopwise, etc.) install.

## SDK — quick start

```bash
pip install pulsewise
```

```python
from pulsewise import PulseClient, EventType

pulse = PulseClient(
    product="voicewise",
    collector_url="https://pulsewise.example.com",
    async_mode=True,
    enabled=True,
)

pulse.track(
    event_type=EventType.VOICE_TRANSCRIPTION,
    session_id=session.id,
    user_id=hashed_user_id,        # never raw PII
    confidence=0.94,
    latency_ms=312,
    model_provider="deepgram",
    cost_usd=0.0021,
    context={"accent_detected": "british"},
)
```

The SDK is **fire-and-forget** in `async_mode=True`: `track()` never blocks the
calling thread. A built-in circuit breaker (5 failures → OPEN for 60s) protects
consumer latency during PulseWise outages.

## Architecture (Phase 1)

| Module | Purpose |
|---|---|
| `core/event_schema.py` | Canonical `PulseEvent` dataclass + validators (1A) |
| `core/otel_genai.py` | Pinned OTel GenAI attribute names (semconv v1.41.1) |
| `ingestion/collector.py` | FastAPI service receiving events, persists to Postgres (1B) |
| `sdk/python/pulsewise.py` | Python SDK, exposed as the top-level `pulsewise` package (1C) |
| `aggregation/summarizer.py` | Hourly job: SQL aggregations + 1 Claude call/product → `insights_summary.json` (1D) |
| `dashboard/` | Static internal dashboard reading `dashboard_data.json` (1E) |

## Admitting a client product

Ingestion rejects any event whose `product` is not on the allowlist. The
allowlist defaults to the five built-in products and is overridden with a
comma-separated env var — admitting a new client is a config change, not a code
change:

```bash
PULSEWISE_VALID_PRODUCTS=hopwise,voicewise,helmerwise,scriptwise,agentwise,via
```

Setting the var **replaces** the default rather than extending it, so list every
product you want admitted. Names are lowercased and capped at 32 characters
(`pulse_events.product` is `VARCHAR(32)`); a longer name is rejected at config
load rather than failing later at INSERT.

### OpenTelemetry GenAI attribute names

Call-level AI context uses OTel GenAI attribute names (`gen_ai.request.model`,
`gen_ai.usage.input_tokens`, `gen_ai.provider.name`, …) so clients emit
vendor-neutral keys. These are **pinned to semantic conventions v1.41.1** and
defined in `core/otel_genai.py` — that module explains why this version and when
to revisit. PulseWise adopts the names only; there is no OpenTelemetry
dependency.

## Hard constraints

- **AI-native events only** — every event must carry meaningful AI context (model,
  confidence, latency, cost) or a clear reason it doesn't.
- **No raw PII** — `user_id` must be hashed by the caller before reaching the SDK.
- **Zero overhead contract** — `async_mode=True` never blocks; circuit breaker
  prevents latency cost during outages.
- **One Claude call per product per aggregation run** — raw event queries are
  pure SQL; LLM is only used for narrative generation.

## Deploying the service

See [DEPLOYMENT.md](DEPLOYMENT.md) for Railway setup.

## Local development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
createdb pulsewise_dev
cp .env.example .env  # edit ANTHROPIC_API_KEY
.venv/bin/uvicorn ingestion.collector:app --host 127.0.0.1 --port 8400
```

Tests:
```bash
createdb pulsewise_test
.venv/bin/python -m pytest tests/
```
