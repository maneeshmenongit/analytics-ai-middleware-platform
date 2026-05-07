# PulseWise — Railway Deployment

This guide walks through deploying the Phase 1 pipeline to Railway as two
services that share one Postgres database:

| Service | Type | Process | Purpose |
|---|---|---|---|
| `pulsewise-collector` | Web service | `uvicorn ingestion.collector:app` | Ingests events, serves `/health`, `/events`, `/insights/{product}`, and the static dashboard at `/dashboard/` |
| `pulsewise-aggregator` | Cron job | `bash scripts/refresh_pipeline.sh` | Hourly: runs the Phase 1D summarizer + regenerates `data/dashboard_data.json` |

Both services are deployed from the **same git repository**.

---

## Prerequisites

- A Railway account with a project (call it `wise-world`)
- An Anthropic API key
- This repo pushed to a remote (GitHub or any Railway-supported provider)

---

## Step 1 — Initialize git and push

The repo isn't a git repo yet:

```bash
git init
git add .
git commit -m "Initial PulseWise Phase 1"
git remote add origin <your-remote-url>
git push -u origin main
```

`.env` is gitignored. Do NOT commit secrets.

---

## Step 2 — Provision the database

In Railway:

1. New Project → **Add Postgres**. Railway sets `DATABASE_URL` automatically on any service in the same project that opts in via service variables.

The collector applies migrations on first boot — no manual `psql` step needed.

---

## Step 3 — Deploy the collector (web service)

1. **New Service → GitHub repo** → select this repo.
2. Service name: `pulsewise-collector`.
3. Railway picks up `railway.toml` automatically. Key bits:
   - Builder: Nixpacks (auto-detects `requirements.txt`)
   - Start command: `uvicorn ingestion.collector:app --host 0.0.0.0 --port ${PORT:-8400} --workers 2 --proxy-headers`
   - Healthcheck path: `/health` (30s timeout)

### Alternative: Dockerfile-based deploy

If you prefer Docker over Nixpacks (more reproducible, easier to test
locally), the repo ships a `Dockerfile` that builds the same service. To
switch:

1. In the Railway service settings, change the **Builder** to "Dockerfile".
   Railway auto-detects the `Dockerfile` at the repo root.
2. The image runs the collector by default (`uvicorn ingestion.collector:app
   ...`). For the aggregator service, override the start command in Railway:
   `bash scripts/refresh_pipeline.sh`.

Local Docker test:
```bash
docker build -t pulsewise:local .
docker run --rm -p 8400:8400 \
    -e DATABASE_URL="postgresql://host.docker.internal:5432/pulsewise_dev" \
    pulsewise:local
curl http://localhost:8400/health
```
4. **Service variables** (Settings → Variables):
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}    # reference the Postgres service
   ANTHROPIC_API_KEY=sk-ant-...               # not required for the collector itself, but harmless
   PULSEWISE_ENV=production
   ```
   Optional:
   ```
   PULSEWISE_INSIGHTS_PATH=/app/data/insights_summary.json
   ```
5. **Generate a public domain** (Settings → Networking → Generate Domain). That URL is your `PULSEWISE_URL` for consumer products.

After deploy, verify:

```bash
curl https://<your-collector>.up.railway.app/health
# {"status":"ok","db":true}
```

The dashboard is at `https://<your-collector>.up.railway.app/dashboard/`.

---

## Step 4 — Deploy the aggregator (scheduled job)

The summarizer + dashboard generator must run **periodically against the same
Postgres**. On Railway, this is a separate service with a cron schedule.

1. **New Service → GitHub repo** (same repo) → name it `pulsewise-aggregator`.
2. **Settings → Deploy → Custom Start Command**:
   ```
   bash scripts/refresh_pipeline.sh
   ```
3. **Settings → Cron Schedule**:
   ```
   0 * * * *
   ```
   (every hour on the hour — matches `AGGREGATION_INTERVAL_MINUTES=60` from the spec)
4. **Service variables**:
   ```
   DATABASE_URL=${{Postgres.DATABASE_URL}}
   ANTHROPIC_API_KEY=sk-ant-...
   PULSEWISE_ENV=production
   ```
5. **Important**: the aggregator writes `data/insights_summary.json` and
   `data/dashboard_data.json` to its **own filesystem**, which the collector
   service cannot read. Two options:
   - **(A) Run the aggregator on the collector service via cron-in-process.** Skip Step 4 entirely; instead use Railway's [scheduled tasks on the same service](https://docs.railway.app/reference/cron-jobs) by adding a second start command. Simpler — both processes share `/app/data`. **Recommended.**
   - **(B) Use a shared volume.** Railway volumes can be mounted across services. Mount `/app/data` to both. More isolation.

Until volume support is wired, prefer **option A**: configure the cron schedule on the **collector** service so the JSON files live on the same disk as the FastAPI process serving `/data/`.

---

## Step 5 — Connect a consumer product

In e.g. VoiceWise's Railway service, add:

```
PULSEWISE_URL=https://<your-collector>.up.railway.app
PULSEWISE_ENABLED=true
```

In VoiceWise code:

```python
from pulsewise import PulseClient, EventType

pulse = PulseClient(
    product="voicewise",
    collector_url=os.environ["PULSEWISE_URL"],
    async_mode=True,
    enabled=os.getenv("PULSEWISE_ENABLED", "true") == "true",
)

pulse.track(
    event_type=EventType.VOICE_TRANSCRIPTION,
    session_id=session.id,
    confidence=0.94,
    latency_ms=312,
    model_provider="deepgram",
)
```

The SDK is now installable as a proper Python package from this repo:

```bash
# Editable install while developing
pip install -e .

# Or build a wheel and install in another project
python -m build --wheel
pip install dist/pulsewise-0.1.0-py3-none-any.whl
```

After install, consumers do `from pulsewise import PulseClient, EventType`
(no relative paths, no submodule). The package is declared in
[pyproject.toml](pyproject.toml). It ships only the SDK + schema —
service code (collector / aggregator / dashboard) is excluded from the wheel.

**Phase 2 packaging note:** the wheel currently exposes three top-level
namespaces (`pulsewise`, `core`, `sdk`) because the shim re-exports across
them. Before publishing to PyPI, restructure into a single `pulsewise/` tree
to avoid polluting consumer namespaces. This is a known followup; documented
in [pulsewise/__init__.py](pulsewise/__init__.py).

---

## Local development

```bash
# 1. Install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. Set up Postgres (one-time)
createdb pulsewise_dev

# 3. Copy env template and fill in your key
cp .env.example .env
# edit .env: set ANTHROPIC_API_KEY at minimum

# 4. Run the collector
.venv/bin/uvicorn ingestion.collector:app --host 127.0.0.1 --port 8400

# 5. In another terminal, run the aggregator on demand
PATH="$PWD/.venv/bin:$PATH" bash scripts/refresh_pipeline.sh

# 6. View the dashboard
open http://127.0.0.1:8400/dashboard/
```

Tests:
```bash
createdb pulsewise_test     # one-time
.venv/bin/python -m pytest tests/ -v
```

---

## Required env vars (summary)

| Var | Required | Used by | Notes |
|---|---|---|---|
| `DATABASE_URL` | yes | collector, aggregator | Hard-fail at collector import if missing |
| `ANTHROPIC_API_KEY` | yes (for narrative) | aggregator | If missing, aggregator falls back to deterministic narrative — does not crash |
| `PULSEWISE_ENV` | no | both | `production` / `development` |
| `PULSEWISE_INSIGHTS_PATH` | no | collector | Override for `/insights/{product}` JSON location |
| `PULSEWISE_URL` | yes (consumer side) | VoiceWise / Hopwise | Where the SDK posts events |
| `PULSEWISE_ENABLED` | yes (consumer side) | VoiceWise / Hopwise | `false` = SDK no-op |
| `PORT` | no (Railway sets it) | collector | Railway-provided |
| `REDIS_URL` | no (Phase 1) | — | Declared for future Redis buffer (Phase 2) |

---

## Failure behavior — verified

- Collector with no `DATABASE_URL`: refuses to start (RuntimeError at import). ✓
- Aggregator with no `ANTHROPIC_API_KEY`: continues with deterministic narrative; never crashes. ✓
- Aggregator with bad Claude response (non-JSON, network error): falls back. ✓
- Collector with Postgres down at runtime: `/health` returns 503, `/events` returns 503, no crash. ✓
- Consumer SDK with collector unreachable: silent drop; circuit breaker opens after 5 failures and drops with <1ms latency for the 60s cooldown window. ✓

---

## Troubleshooting

**`/dashboard/` shows "loading…" forever.** The dashboard's JS fetches
`../data/dashboard_data.json`. If the aggregator hasn't run yet, that file
doesn't exist. Run `bash scripts/refresh_pipeline.sh` once.

**"narrative is null" on `/insights/{product}`.** Same root cause — the
summarizer hasn't written `data/insights_summary.json`. Run the aggregator.

**Pool warnings on shutdown.** Harmless; psycopg's pool announces unclosed
threads when uvicorn workers terminate hard. Doesn't affect correctness.

**Aggregator runs but Claude isn't called.** Check the logs for
`ANTHROPIC_API_KEY not set — skipping Claude narrative`. The aggregator runs
in fallback mode whenever the key is missing or the call fails.
