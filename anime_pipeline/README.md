# Anime Pipeline

A multi-agent backend for a serialized anime YouTube channel: thirteen agents,
a gated episode workflow, schema-enforced handoffs, and a QC model that decides
whether an episode ships.

Provider-neutral by design — no LLM or media provider is wired in. Implement
`LLMProvider` / `MediaProvider` in `app/services/provider_router.py` when you
pick one.

## Run it

```bash
pip install -e ".[dev]"
alembic upgrade head          # creates the schema and seeds the 13 agents
uvicorn app.main:app --reload
pytest                        # 167 tests, no network or database needed
```

Defaults to SQLite so it runs with no infrastructure. Point at Postgres for
anything real — the models switch to native UUIDs and JSONB automatically:

```bash
export ANIME_DATABASE_URL=postgresql+psycopg://user:pass@localhost/anime
```

| Variable | Default | Purpose |
|---|---|---|
| `ANIME_DATABASE_URL` | `sqlite:///./anime_pipeline.db` | Database |
| `ANIME_FRAME_RATE` | `24` | Project frame rate for QC timing notes |
| `ANIME_LLM_PROVIDER` | unset | Selects the LLM provider once one is implemented |
| `ANIME_ECHO_SQL` | unset | Log SQL |

## Layout

```
app/
  models/       enums, task envelope, inter-agent messages, HTTP models
  schemas/      agent output contracts + the schema registry
  db/           SQLAlchemy models
  services/     orchestrator, agent runner, provider router
  agents/       agent registry + 13 system prompts
  api/routes/   episodes, tasks, qc_reports, pipeline, webhooks
migrations/     alembic
tests/          167 tests
```

## The four ideas worth knowing

**1. The pipeline is data, not code.** `PIPELINE` in
`app/services/orchestrator.py` declares fifteen stages with their agents,
schemas, dependencies and gates. `validate_pipeline()` rejects cycles and
dangling references at import. `GET /pipeline/stages` serves the same
declaration, so n8n or LangGraph can drive the graph without re-encoding it.

**2. Nothing crosses an agent boundary unvalidated.** Every task names an
`output_spec.schema_name`; the name is checked when the task is built, not after
a provider call has been paid for. Output that fails its schema is retried once
with the validation error fed back, then escalated — and is never stored, so a
downstream agent cannot read a payload that broke its own contract.

**3. Workflow state is durable and serialised.** `WorkflowState` lives in
Postgres, not in a worker's memory. Every event is handled inside a per-episode
`SELECT ... FOR UPDATE`, so two workers touching the same episode serialise
instead of losing each other's writes, and an episode's progress survives a
restart. The orchestrator itself stays database-free — `WorkflowStateRepository`
is the only seam.

**4. QC scores are computed, never asserted.** `overall_score`,
`anime_style_score` and `publish_ready` are derived from the twelve category
scores on every validation, including on read. An agent — or a hand-edited
database row — cannot claim a passing total alongside failing sections.

**5. Every gate is checked by an adversarial suite.** A gate that wrongly
blocks generates a complaint; a gate that wrongly *passes* generates nothing at
all. `POST /evaluation/runs` runs 18 cases against the live deployment, half of
which assert nothing fires — because a matcher that blocks every change would
score 100% on a suite made only of real contradictions.

**6. Rewriting canon is possible, but never silent.** Contradictions still
block. An editor unblocks one change by approving a retcon proposal that records
who decided and why; the superseded fact is closed, not deleted.

## Endpoints

| Route | Purpose |
|---|---|
| `POST /episodes/` · `GET /episodes/{code}` | Episode CRUD |
| `POST /tasks/` · `POST /tasks/{code}/complete` | Task intake, schema-checked completion |
| `POST /qc-reports/` | Submit a QC report; scores computed server-side |
| `GET /qc-reports/episode/{code}/publish-gate` | Ship it or not, and why not |
| `GET /memory/bundles/agent/{code}` | Everything an agent must read before working |
| `POST /memory/consistency-check` | Audit a draft script against canon |
| `POST /memory/writeback` | Fold an approved artifact into canon |
| `POST /canon/preflight` | Refuse a task whose required canon is missing |
| `POST /canon/validate-draft` | Guard + contradiction check over a draft |
| `POST /canon/contradiction-check` | Proposed facts vs established canon |
| `POST /canon/entities` · `/canon/timeline` | Registry and chronology |
| `POST /canon/aliases` · `GET /canon/entities/{series}/suggest` | Spellings, and near misses for a human |
| `POST /canon/timeline/rebalance` | Respace order indexes without reordering |
| `POST /canon/causal-links` · `GET /canon/causal-check/{series}` | Cause → effect edges and their impossibilities |
| `POST /canon/retcons` · `/retcons/{code}/approve` | File and decide a sanctioned rewrite of canon |
| `POST /evaluation/runs` · `GET /evaluation/suite` | Run the adversarial continuity suite |
| `GET /pipeline/stages` · `/agents` · `/qc-model` · `/diagram` | The graph, introspectable |
| `POST /webhooks/events` · `GET /webhooks/state/{code}` | Orchestrator events |

## Documentation

- [Orchestration](../docs/anime-pipeline/01-orchestration.md) — graph, state machine, gates, events
- [QC framework](../docs/anime-pipeline/02-qc-framework.md) — weights, thresholds, the publish gate
- [Anime edit checklist](../docs/anime-pipeline/03-anime-edit-checklist.md) — frame-accurate timings
- [Tracker schemas](../docs/anime-pipeline/04-tracker-schemas.md) — Notion / Airtable
- [Canon memory](../docs/anime-pipeline/05-canon-memory.md) — drift prevention, consistency guard, writeback
- [Continuity enforcement](../docs/anime-pipeline/06-continuity-enforcement.md) — registry, timeline, contradictions, the three gates
- [Continuity hardening](../docs/anime-pipeline/07-continuity-hardening.md) — normalisation, aliases, retcon approvals, causality, the adversarial suite

## What is scaffolding

Two things are deliberately unfinished, and both are marked in the source:

- **No provider is wired.** `StubLLMProvider` returns canned responses so the
  orchestrator is testable. `ProviderRouter` raises
  `ProviderNotConfiguredError` rather than silently no-op'ing.
- **The Postgres integration tests have not been observed passing.** They skip
  when no database is available, which is the case in the environment they were
  written in. `tests/test_postgres_integration.py` documents how to give them
  one; everything else runs on SQLite.

Everything else — schema enforcement, gating, scoring, state persistence,
migrations — is complete and covered by tests.
