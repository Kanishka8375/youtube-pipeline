# Anime Pipeline

A multi-agent backend for a serialized anime YouTube channel: thirteen agents,
a gated episode workflow, schema-enforced handoffs, a QC model that decides
whether an episode ships, an enforced continuity canon, and real LLM providers
behind a durable job queue.

An admin console lives in [`../frontend`](../frontend).

## Run it

```bash
pip install -e ".[dev]"
alembic upgrade head          # creates the schema and seeds the 13 agents
uvicorn app.main:app --reload
pytest                        # 324 tests, no network or database needed
```

No API key is needed to run the whole pipeline end to end: the `mock` provider
is deterministic and always ready. Set `ANTHROPIC_API_KEY` when you want real
generation.

Defaults to SQLite so it runs with no infrastructure. Point at Postgres for
anything real — the models switch to native UUIDs and JSONB automatically:

```bash
export ANIME_DATABASE_URL=postgresql+psycopg://user:pass@localhost/anime
```

| Variable | Default | Purpose |
|---|---|---|
| `ANIME_DATABASE_URL` | `sqlite:///./anime_pipeline.db` | Database |
| `ANIME_FRAME_RATE` | `24` | Project frame rate for QC timing notes |
| `ANIME_ECHO_SQL` | unset | Log SQL |
| `ANIME_SECRET_KEY` | insecure dev default | Signs bearer tokens. **Required** when `ANIME_ENV` is production |
| `ANIME_ENV` | `local` | `production`/`prod`/`staging` make the startup secret check fatal |
| `ANIME_TOKEN_TTL_MINUTES` | `1440` | Token lifetime |
| `ANIME_CORS_ORIGINS` | `http://localhost:3001` | Comma-separated admin console origins |
| `ANTHROPIC_API_KEY` | unset | Enables the `anthropic` provider |
| `ANIME_OPENAI_BASE_URL` · `_API_KEY` · `_MODEL` | unset | Any OpenAI-compatible endpoint (vLLM, Ollama, Groq) |
| `ANIME_STORAGE_PROVIDER` · `_ROOT` | `local` · `./storage` | Where generated media lands |

## Layout

```
app/
  core/         config, database, security (hashing + token signing), logging
  models/       enums, task envelope, inter-agent messages, HTTP models
  schemas/      agent output contracts + the schema registry
  db/           SQLAlchemy models (36 tables)
  services/
    auth/       password hashing, tokens, the role ladder
    workspaces/ membership, roles, config profiles
    jobs/       the database-backed queue
    audit/      who decided what
    generation/ providers, prompt templates, canon-bound prompt building
    ...         orchestrator, canon registry, contradiction, retcon, evaluation
  agents/       agent registry + 13 system prompts
  api/routes/   episodes, tasks, qc_reports, pipeline, memory, canon,
                evaluation, auth, workspaces, jobs, generation, system, webhooks
migrations/     alembic, through 0008
tests/          324 tests
```

## The ideas worth knowing

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

**7. Canon constrains generation before the call, not after.** The obvious
wiring — generate, then reject what breaks canon — wastes the call and creates
pressure to approve a draft everyone already likes. Instead `CanonPromptBuilder`
renders established facts *into* the prompt, marking each `(fixed)` or
`(as of now)` so the model can tell what is negotiable. The gates remain, as a
backstop. `POST /generation/preview` shows the exact prompt without spending a
token.

**8. A non-member gets 404, not 403.** A 403 would confirm the workspace exists,
which for a private show is the leak. Once membership is established an
insufficient role does return 403 — the caller already knows it exists.

**9. The retry budget is committed before the handler runs.** A failing handler
leaves the session dirty, so the queue must roll back to record the failure —
and that rollback would undo an uncommitted attempt increment, so the budget
would never deplete and a permanently broken job would retry forever. See
`app/services/jobs/job_queue.py`.

**10. One correlation id spans request, job and worker log line.** Otherwise
"why did this episode fail" means correlating two processes by timestamp, which
works right up until two requests arrive in the same second.

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
| `POST /auth/register` · `/auth/login` · `GET /auth/me` | Identity |
| `POST` · `GET /workspaces` · `/{slug}/members` · `/audit-log` | Workspaces, roles, who decided what |
| `PUT` · `GET /workspaces/{slug}/config-profiles` | Per-workspace settings; secret-looking keys refused |
| `POST` · `GET /jobs` · `/jobs/{id}` · `/jobs/drain` | The queue: enqueue, inspect, run now |
| `GET /generation/templates` · `/providers` | What can be generated, and with what |
| `POST /generation/preview` | The real canon-bound prompt, without spending a token |
| `POST /generation/run` | Resolve the provider, then enqueue |
| `GET /system/health` · `/system/readiness` | Liveness, and whether dependencies answer |

## Documentation

- [Orchestration](../docs/anime-pipeline/01-orchestration.md) — graph, state machine, gates, events
- [QC framework](../docs/anime-pipeline/02-qc-framework.md) — weights, thresholds, the publish gate
- [Anime edit checklist](../docs/anime-pipeline/03-anime-edit-checklist.md) — frame-accurate timings
- [Tracker schemas](../docs/anime-pipeline/04-tracker-schemas.md) — Notion / Airtable
- [Canon memory](../docs/anime-pipeline/05-canon-memory.md) — drift prevention, consistency guard, writeback
- [Continuity enforcement](../docs/anime-pipeline/06-continuity-enforcement.md) — registry, timeline, contradictions, the three gates
- [Continuity hardening](../docs/anime-pipeline/07-continuity-hardening.md) — normalisation, aliases, retcon approvals, causality, the adversarial suite
- [Access control and deferred work](../docs/anime-pipeline/08-access-and-jobs.md) — passwords, tokens, workspaces, the job queue, correlation ids
- [Generation integration](../docs/anime-pipeline/09-generation-integration.md) — providers, prompt templates, canon-bound prompts, provenance
- [Admin console](../docs/anime-pipeline/10-admin-console.md) — the Next.js front end

## What is scaffolding

Marked in the source, and worth knowing before you rely on any of it:

- **Only text generation is wired.** `anthropic` and any OpenAI-compatible
  endpoint work end to end. Image, video and music providers are still
  interfaces — `ProviderRouter` raises `ProviderNotConfiguredError` rather than
  silently no-op'ing.
- **Storage is local-disk only.** `ANIME_STORAGE_PROVIDER=local` is the only
  implementation; S3 and GCS are seams, not adapters.
- **No YouTube upload adapter.** The pipeline ends at an approved artifact.
- **No websocket streaming.** The console polls, and pauses polling when its tab
  is hidden.
- **The Postgres integration tests have not been observed passing.** They skip
  when no database is available, which is the case in the environment they were
  written in. `tests/test_postgres_integration.py` documents how to give them
  one; everything else runs on SQLite.

Everything else — schema enforcement, gating, scoring, state persistence,
migrations — is complete and covered by tests.
