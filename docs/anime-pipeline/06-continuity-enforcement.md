# Continuity Enforcement

Three gates around creative work, plus the registry and timeline that make
contradictions detectable at all.

Implementation: `anime_pipeline/app/services/canon_registry.py`,
`contradiction.py`, `enforcement.py`.

---

## Why a naive contradiction matcher fails

The obvious rule — *same entity, same fact key, different value ⇒ contradiction*
— flags every normal story development. Mira's trust in Kade going from
`intact` to `damaged` **is the plot**, not an error. A gate built that way
blocks on ordinary progression, gets switched off within a week, and then
protects nothing.

The distinction that makes it work lives on the fact:

| `mutability` | Meaning | A change is |
|---|---|---|
| `immutable` | Cannot change without rewriting the past: a birth name, a species, what happened in EP03 | a **contradiction**, blocking |
| `stateful` | Changes as the story runs: trust, location, injuries, what a character knows | **progression**, reported not blocked |

Two refinements matter:

- **The stored fact governs.** If canon holds a fact as `immutable`, a draft
  claiming `stateful` does not get past the gate. Otherwise any agent could
  relabel canon as mutable to avoid the check.
- **Unclassified facts default to `immutable`.** The conservative direction: an
  unclassified fact is flagged when it changes rather than passed silently.

### Retcons

One case makes a *stateful* change a contradiction: establishing it from an
episode that sits **earlier** on the timeline than the one that established the
current value. That is writing new past over settled future. Detecting it is
the reason the timeline exists.

```
EP01 (order 1) ── EP02 (order 2) establishes location = safehouse
       ▲
       └─ a later draft for EP01 sets location = transit station  → retcon
```

## The registry, and why free text is not enough

Facts key off `entity_key`, written by agents. Without normalising through a
registry, `"MIRA"` and `"Mira"` are different entities that can never
contradict each other — canon forks silently and nothing ever fires.

`canonical_entities` gives one record per named thing, scoped per series.
Resolution matches code, display name and aliases, case-insensitively, on both
the proposed fact *and* every stored fact, so facts written before an entity
was registered still meet it afterwards.

Two rules keep it honest:

- **Ambiguity raises.** A name matching two entities is refused, not guessed.
  Attaching a fact to the wrong entity is worse than refusing: it would then
  never contradict anything.
- **Unregistered keys pass through**, and are reported under
  `unregistered_entities`. Canon can be recorded about something not yet
  registered; it just does not get cross-spelling matching until it is.

```
GET /canon/entities/{series_code}/resolve?name=Mira Kisaragi
POST /canon/entities
POST /canon/timeline        GET /canon/timeline/{series_code}
POST /canon/contradiction-check
```

`order_index` is unique per series. Without that constraint two events can tie
and "ordered" stops being a well-defined word — the timeline differs between
reads.

## The three gates

### 1. Preflight — before a task runs

```
POST /canon/preflight  {"agent_code": ..., "episode_code": ...}
```

Refuses to start a task whose required canon is missing. **An agent with no
style bible does not fail loudly — it invents one**, and that invention becomes
the thing the next episode is consistent with.

Each agent declares what it needs in `REQUIRED_COMPONENTS`. Two are tested as
invariants: every declared requirement has a check, and every pipeline agent
has an entry. `analytics_optimization_agent` declares `()` — deliberately
nothing, which is different from never having been considered.

### 2. Draft validation — on a produced draft

```
POST /canon/validate-draft
```

Runs the **existing** consistency guard (reused, not reimplemented — a second
copy would drift from the one with the tests) and the contradiction matcher,
records both as `continuity_issues`, and returns:

- `issues` — what fired, with `blocking` per issue
- `not_mechanically_checked` — prose rules only the QC agent can judge
- `unknown_speakers`, `unregistered_entities` — the usual first signs of drift
- `progressions` — stateful changes, so canon moving is visible without blocking

A pass means *nothing mechanically checkable failed*, never *this is
consistent*. See [05-canon-memory.md](05-canon-memory.md#the-consistency-guard).

### 3. Writeback — after approval

```
POST /canon/writeback  {"output_type": "script" | "qc_report" | "final_cut_metadata" | "packaging", ...}
```

| Output type | Yields |
|---|---|
| `script` | canon facts, character state changes, hooks, style candidates |
| `qc_report` | **style candidates only** — never canon facts |
| `final_cut_metadata` | facts, state changes, music and visual motifs |
| `packaging` | packaging style candidates |

A repeated edit complaint in a QC report is evidence a rule may be missing from
the style bible. It is *not* a fact about the world, and must not become one
automatically.

**Style candidates are never applied.** They come back under
`style_candidates_awaiting_approval`. Style is a showrunner decision, and a rule
inferred from one episode's QC notes is a hypothesis.

An unsupported `output_type` is a 400, not a silent empty parse.

## Publish gate

`enforcement_clear` is now a fifth check on the existing gate:

| Check | Passes when |
|---|---|
| `qc_score_ok` | Final-cut score ≥ `PUBLISH_SCORE_THRESHOLD` (85) |
| `mandatory_fixes_closed` | No outstanding required fixes |
| `no_critical_issues` | No critical issues |
| `continuity_passed` | A passing continuity check exists |
| `enforcement_clear` | No unresolved blocking issues or contradictions |

The threshold still lives in exactly one constant. An episode can hold a
passing consistency check and still carry an unresolved retcon raised by a
later draft validation, which is why enforcement is its own check rather than
folded into `continuity_passed`.

## Operational flow

```
preflight  →  agent works  →  validate-draft  →  approval  →  writeback
                                    ↓                            ↓
                            blocking issues              canon facts,
                            recorded                     state, hooks
                                    └──────────┬─────────────────┘
                                          publish gate
```

## What is stored per run

`continuity_enforcement_runs.memory_provenance` holds the memory codes and
versions a run read — not the bundle itself. The bundle carries every character
profile and the whole style bible; storing it per run would balloon the table
while answering the same question ("which canon was this judged against?").

There is deliberately **no numeric run score**. `100 - issues × 15` makes seven
nits and one retcon look identical, and a number that misleads is worse than
counts that don't.
