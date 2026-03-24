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
| `JEAN_FLOWFABRIC_WEBHOOK` | — | FlowFabric notification URL (optional) |

---

## Project Status

**v0.1.0 — Core engine bootstrapped.**

| Component | Status |
|-----------|--------|
| Data models (Pydantic v2) | ✅ BusinessEvent, SessionTrace, PatternHypothesis, FieldObservation |
| jean-agent LocalBuffer (SQLite, offline-first) | ✅ |
| jean-agent EventEmitter (HTTP flush with backoff) | ✅ |
| jean-agent AppTransitionCapture (macOS) | ✅ stub (requires pyobjc) |
| jean-aggregator FastAPI (ingest + patterns) | ✅ |
| jean-aggregator Anonymizer | ✅ configurable PII field list |
| jean-aggregator PatternDetector | ✅ sliding-window n-gram |
| jean-corpus-feeder KFabricAdapter | ✅ mock implementation |
| jean-validator | 🔜 FlowFabric integration (next milestone) |
| macOS NSWorkspace capture | 🔜 requires pyobjc (next milestone) |
| GitHub Actions CI | ✅ `.github/workflows/ci.yml` |
| Prometheus metrics | ✅ `GET /metrics` on aggregator (8100) and validator (8200) |
| KFabric HTTP adapter | ✅ `HttpKFabricAdapter` — real HTTP client, `MockKFabricAdapter` default |
| Validator UI | ✅ `GET /ui/` — approve/reject interface, no build step |
| Tests | ✅ 74 passing (models, buffer, anonymizer, detector, store, ERP, validator, pipeline, bridge, adapter, metrics) |

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
