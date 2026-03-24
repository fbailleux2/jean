# Jean

[![CI](https://github.com/fbailleux2/jean/actions/workflows/ci.yml/badge.svg)](https://github.com/fbailleux2/jean/actions/workflows/ci.yml)

**The silent observer that turns the gap between what your organization says it does and what it actually does into governed intelligence.**

Jean is the lightweight, event-driven field observer of the [Fabric cognitive OS](https://github.com/fbailleux2/flowfabric). It captures the divergence between formal procedures and real field practices, and feeds it — after human validation — into FlowFabric's knowledge corpus.

> Jean is not a surveillance tool. It is the employee's assistant and the governed sensor of real processes.

---

## The Fabric Ecosystem

```
┌──────────────────────────────────────────────┐
│  FlowFabric  — Orchestration & governance    │
├──────────────────────────────────────────────┤
│  BundleFabric — Agent/tool packaging         │
├──────────────────────────────────────────────┤
│  KFabric      — Corpus & knowledge           │
└──────────────────────────────────────────────┘
         ↑ fed by Jean (field observer)         ← this repo
```

---

## Architecture

Jean is decomposed into five sub-components plus a bridge:

| Component | Role | Deployment |
|-----------|------|------------|
| `jean-agent` | Minimal local event capture | Per workstation (macOS MVP) |
| `jean-aggregator` | Aggregation, anonymization, pattern detection | Centralized (port 8100) |
| `jean-validator` | Human validation + corpus submission | Standalone API (port 8200) |
| `jean-corpus-feeder` | Governed feeding of KFabric | Called by validator |
| `jean-bridges/flowfabric` | Fire-and-forget FlowFabric notification | Embedded in validator |

### Full event flow

```
Workstation
  jean-agent (app transitions, structural actions)
    ↓ HTTP batch (offline-first SQLite buffer)

jean-aggregator (port 8100)
  POST /ingest        → Anonymizer → InMemoryStore / PostgresStore
  POST /connectors/erp/events → BusinessEvent mapper
  GET  /patterns      → PatternDetector (sliding-window n-gram)
    ↓ PatternHypothesis → FieldObservation

jean-validator (port 8200)
  POST /observations/{id}/approve
    → VALIDATED state
    → CorpusPipeline.run() → KFabricAdapter (mock or real)
    → FlowFabricBridge.notify() (fire-and-forget, optional)
  POST /observations/{id}/reject → stores rejection_reason in metadata
```

---

## What Jean captures

| Signal | Captured | Excluded |
|--------|----------|---------|
| Application focus transitions | ✅ App name only | Window title, document name |
| Structural actions (save, submit, export, print) | ✅ Action type + app | Document content |
| ERP events | ✅ Structured fields | Free-text notes |
| Operator annotations (explicit) | ✅ Text entered in FlowFabric Inbox | — |
| Continuous screen capture | ❌ Never | — |
| Keylogging | ❌ Never | — |
| Personal communications | ❌ Never | — |

---

## Quick Start

```bash
git clone https://github.com/fbailleux2/jean.git && cd jean
pip install uv && uv sync --dev
uv run pytest tests/ -q         # all tests green
```

Or with Docker Compose:

```bash
docker compose up --build
# aggregator → http://localhost:8100
```

### Environment variables

See `.env.example` for a full list. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `JEAN_AGGREGATOR_URL` | `http://localhost:8100` | jean-aggregator endpoint |
| `JEAN_STORE` | `memory` | Aggregator store: `memory` or `postgres` |
| `JEAN_PG_DSN` | — | PostgreSQL DSN (when `JEAN_STORE=postgres`) |
| `JEAN_PROCESS_CONTEXT` | `default` | Business process being observed |
| `JEAN_WORKSTATION_ID` | random UUID | Pseudonymous workstation identifier |
| `JEAN_BUFFER_PATH` | `jean-agent.db` | SQLite buffer path |
| `JEAN_API_KEY` | — | X-API-Key for protected routes (unset = auth disabled) |
| `JEAN_VALIDATOR_URL` | — | Validator URL for auto-observation dispatch (unset = disabled) |
| `JEAN_OBS_THRESHOLD` | `0.7` | Min confidence to auto-generate FieldObservations |
| `JEAN_OBS_STORE_PATH` | — | SQLite path for validator persistence (unset = in-memory) |
| `JEAN_FLOWFABRIC_WEBHOOK` | — | FlowFabric notification URL (optional) |
| `JEAN_KFABRIC_URL` | — | KFabric ingest URL (unset = MockKFabricAdapter) |
| `JEAN_KFABRIC_API_KEY` | — | Bearer token for KFabric API auth (unset = no auth) |

---

## Project Status

**v0.9.0 — Full capture stack + KFabric auth.**

| Component | Status |
|-----------|--------|
| Data models (Pydantic v2) | ✅ BusinessEvent, SessionTrace, PatternHypothesis, FieldObservation |
| jean-agent LocalBuffer (SQLite, offline-first) | ✅ |
| jean-agent EventEmitter (HTTP flush with backoff) | ✅ |
| jean-agent AppTransitionCapture — macOS | ✅ NSWorkspace via pyobjc (`uv sync --extra macos`) |
| jean-agent AppTransitionCapture — Linux | ✅ `_linux.py` — xdotool polling, process name via /proc |
| jean-agent AppTransitionCapture — Windows | ✅ `_windows.py` — Win32 ctypes polling, no pywin32 needed |
| jean-agent KeyboardCapture | ✅ pynput-based hotkeys wired into `main.py` (Ctrl+S/P/Shift+E) |
| jean-aggregator FastAPI (ingest + patterns) | ✅ |
| jean-aggregator Anonymizer | ✅ configurable PII field list |
| jean-aggregator PatternDetector | ✅ sliding-window n-gram |
| jean-corpus-feeder HttpKFabricAdapter | ✅ real HTTP client, retry on 5xx, `JEAN_KFABRIC_API_KEY` Bearer auth |
| jean-corpus-feeder MockKFabricAdapter | ✅ in-memory default when `JEAN_KFABRIC_URL` unset |
| KFabric mock service | ✅ `services/kfabric-mock/` — FastAPI with `/ingest`, `/health`, `/entries` |
| jean-validator REST API | ✅ observe / approve / reject / register routes |
| jean-validator UI | ✅ `GET /ui/` — approve/reject interface, no build step |
| jean-validator Persistence | ✅ `SQLiteObservationStore` — `JEAN_OBS_STORE_PATH` env var (in-memory default) |
| jean-validator startup health check | ✅ KFabric health check logged on startup (warn, never fail) |
| FlowFabric bridge — bi-directional | ✅ `notify()` sends callback_url; `POST /webhook/flowfabric` handles approve/reject |
| FlowFabric bridge — retry | ✅ 3 attempts, 1s/2s/4s backoff on 5xx |
| GitHub Actions CI | ✅ `.github/workflows/ci.yml` |
| Prometheus metrics | ✅ `GET /metrics` on aggregator (8100) and validator (8200) |
| End-to-end integration test | ✅ `tests/test_integration.py` — full pipeline from buffer to approval |
| macOS thread bridge fix | ✅ `asyncio.get_running_loop()` replaces deprecated `get_event_loop()` |
| DPIA template | ✅ `docs/dpia-template.md` + `docs/consent-notice-template.md` |
| API Key Auth | ✅ `X-API-Key` on all mutating routes — `JEAN_API_KEY` env var |
| Auto-Observations | ✅ `ObservationGenerator` — patterns above threshold → FieldObservations dispatched in background |
| Query Filters | ✅ `GET /patterns?process_context=X`, `GET /observations?limit=N&offset=N` |
| Agent Smoke Test | ✅ `scripts/smoke_test_agent.py --dry-run` |
| Tests | ✅ 169 passing, 1 skipped (pynput on macOS) |

---

## API Key Authentication

Protected routes (`POST /ingest`, `POST /connectors/erp/events`, `POST /observations/{id}/approve`, `POST /observations/{id}/reject`) require an `X-API-Key` header when `JEAN_API_KEY` is set.

Public routes (`GET /health`, `GET /metrics`, `GET /observations`) require no key.

```bash
# Set in production
export JEAN_API_KEY=my-secret-key

# Call a protected route
curl -X POST http://localhost:8100/ingest \
  -H "X-API-Key: my-secret-key" \
  -H "Content-Type: application/json" \
  -d '[...]'
```

Error responses: `401 Unauthorized` (missing header) · `403 Forbidden` (wrong key)

---

## Validator Persistence

By default, jean-validator keeps observations in memory (lost on restart). Set `JEAN_OBS_STORE_PATH` to a file path to enable SQLite persistence:

```bash
export JEAN_OBS_STORE_PATH=/data/observations.db
```

In Docker Compose this is already configured with a named volume (`validator-data`).

---

## Query Filters

```bash
# Patterns for a specific process context
GET /patterns?process_context=invoice-exception

# Paginated observations (newest UI pattern: offset=0 limit=20)
GET /observations?state=observed&limit=20&offset=0
```

---

## Auto-Observations

After each `/ingest` call, the aggregator runs `ObservationGenerator` on the detected patterns. Any `PatternHypothesis` with `confidence >= JEAN_OBS_THRESHOLD` (default `0.7`) is converted into a `FieldObservation` and POSTed to `JEAN_VALIDATOR_URL/observations/register`.

The dispatch is **fire-and-forget**: failures are logged but never propagate to the caller. If `JEAN_VALIDATOR_URL` is unset, dispatch is skipped entirely.

```
POST /ingest
  → Anonymizer
  → Store
  → PatternDetector
  → ObservationGenerator (confidence >= 0.7)
  → ObservationDispatcher → jean-validator POST /observations/register
```

---

## KFabric Integration

Jean feeds validated observations to KFabric via `HttpKFabricAdapter`. Set `JEAN_KFABRIC_URL` to connect to a real KFabric instance:

```bash
export JEAN_KFABRIC_URL=http://kfabric:8300
export JEAN_KFABRIC_API_KEY=your-kfabric-token   # optional Bearer auth
```

When `JEAN_KFABRIC_URL` is unset (default), `MockKFabricAdapter` is used — observations are stored in-memory and no HTTP calls are made. This is the safe default for development.

The adapter retries 5xx errors with exponential backoff (3 attempts: 0.5s / 1s / 2s). 4xx errors (bad request) raise `ValueError` immediately with no retry.

At startup, `jean-validator` checks KFabric `/health` and logs the result. A failing health check never blocks startup — it is a warning only.

### Local KFabric mock service

For integration testing with a real HTTP backend without deploying KFabric:

```bash
docker compose up kfabric-mock
# POST http://localhost:8300/ingest
# GET  http://localhost:8300/health
# GET  http://localhost:8300/entries
```

---

## Cross-Platform Capture

| Platform | App transitions | Hotkeys |
|----------|----------------|---------|
| macOS | ✅ NSWorkspace (`uv sync --extra macos`) | ✅ pynput (`uv sync --extra capture`) |
| Linux | ✅ xdotool polling (`sudo apt install xdotool`) | ✅ pynput |
| Windows | ✅ Win32 ctypes polling (no extra deps) | ✅ pynput |

Linux capture falls back gracefully with a warning if xdotool is not installed. Windows capture uses only standard-library ctypes — no pywin32 required.

---

## End-to-End Testing

`tests/test_integration.py` exercises the complete pipeline in-process:

```
LocalBuffer (agent) → aggregator /ingest → PatternDetector
  → ObservationGenerator → validator /observations/register
  → /observations/{id}/approve → CorpusPipeline
```

Run with: `uv run pytest tests/test_integration.py -v`

---

## Legal / GDPR

See [`docs/dpia-template.md`](docs/dpia-template.md) for a DPIA template aligned with
GDPR Art. 35 and CNIL guidelines.

See [`docs/consent-notice-template.md`](docs/consent-notice-template.md) for an employee
information notice template to distribute before any real deployment.

> ⚠️ Templates only — consult a qualified DPO before processing employee data.

---

## macOS Capture Setup

See [docs/macos-capture.md](docs/macos-capture.md) — covers Accessibility permissions, pyobjc install, and how to verify live capture.

## Design Decisions

**Why SQLite for the local buffer?** Zero dependencies, offline-first, async via aiosqlite. Works on every OS. No daemon required.

**Why event-driven and not continuous?** Continuous capture is legally disproportionate (CNIL sanction Feb 4, 2025 — €40k). Process patterns emerge from structural transitions, not raw streams.

**Why app name only and not window title?** Window titles often contain document names (invoice numbers, client names) — PII risk. Only the application name is needed to detect process transitions.

**Why is the anonymizer in the aggregator, not the agent?** The agent's scope is minimal capture and buffering. The aggregator is the single point responsible for data governance before corpus ingestion.

---

## Legal Notice

Jean is designed for GDPR / CNIL compliance. Before any deployment involving employee data:
- Define the legal basis per treatment
- Inform employees of the nature and scope of collection
- Run a DPIA if required
- Consult employee representatives if required

See `VISION.md` in [FlowFabric](https://github.com/fbailleux2/flowfabric) for the full legal framework.

---

## License

Apache 2.0 — see [LICENSE](LICENSE).

---

*Jean — 2026 — [github.com/fbailleux2/jean](https://github.com/fbailleux2/jean)*
