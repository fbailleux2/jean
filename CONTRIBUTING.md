# Contributing to Jean

## Dev setup

```bash
git clone https://github.com/fbailleux2/jean.git && cd jean
pip install uv
uv sync --dev --extra dev
uv run pytest tests/ -q        # 75+ tests, all green
```

## Project structure

```
src/jean/
├── models.py               — Core Pydantic v2 data models
├── agent/                  — Local event capture + SQLite buffer
│   ├── buffer.py           — LocalBuffer (aiosqlite, offline-first)
│   ├── capture.py          — AppTransitionCapture, StructuralActionCapture
│   ├── emitter.py          — EventEmitter (HTTP flush)
│   └── _macos.py           — NSWorkspace bridge (requires pyobjc)
├── aggregator/             — Centralized ingest, anonymization, patterns
│   ├── api.py              — FastAPI app (port 8100)
│   ├── anonymizer.py       — PII stripping
│   ├── pattern_detector.py — Sliding-window n-gram pattern detection
│   └── store.py            — AbstractStore, InMemoryStore, PostgresStore
├── connectors/             — External system adapters
│   └── erp_webhook.py      — Generic ERP event mapper
├── corpus_feeder/          — KFabric submission
│   ├── adapter.py          — KFabricAdapter, Mock, Http implementations
│   └── pipeline.py         — CorpusPipeline (validated obs → KFabric)
├── validator/              — Human validation circuit
│   ├── api.py              — FastAPI app (port 8200)
│   └── static/index.html   — Minimal UI (no build step)
└── bridges/
    └── flowfabric.py       — Fire-and-forget FlowFabric webhook
```

## Running the full stack

```bash
# Development (in-memory store, no PostgreSQL needed)
uv run jean-aggregator &   # port 8100
uv run jean-validator  &   # port 8200 — UI at http://localhost:8200/ui/
uv run jean-agent          # workstation agent

# Production (with PostgreSQL)
docker compose up --build
```

## Environment variables

See `.env.example` for the full list.

## Adding a new workflow / connector

1. Implement the `RuntimeAdapter` protocol in `src/jean/connectors/`
2. Mount the router in `aggregator/api.py`
3. Add tests in `tests/`
4. Run `uv run pytest` — all tests must pass before opening a PR

## Non-negotiable invariants

Before contributing, read `INVARIANTS.md` in the FlowFabric repo.
Jean is governed by the same principles:

- No keylogging, no continuous capture, no PII outside the anonymizer
- Every observation must go through human validation before corpus ingestion
- No autonomous modification of workflows or procedures

## macOS capture setup

See [docs/macos-capture.md](docs/macos-capture.md).
