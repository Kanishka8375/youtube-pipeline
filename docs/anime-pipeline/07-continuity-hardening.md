# Continuity Hardening

Everything in `06-continuity-enforcement.md` assumes two comparisons work:
that two spellings of a name meet, and that two writings of a value meet.
Neither did. This layer makes them work, adds a sanctioned way to rewrite
canon on purpose, extends chronology with causality, and puts a standing
adversarial suite behind all of it.

Implementation: `anime_pipeline/app/services/normalisation.py`,
`canon_registry.py`, `contradiction.py`, `retcon.py`, `evaluation.py`,
`benchmarks.py`. Migrations `0006` and `0007`.

---

## 1. Normalisation — the comparison everything rests on

Both halves of the matcher were comparing raw text.

**Names.** `"Mira"`, `"MIRA"` and `"Mira "` resolved separately, so canon
forked into parallel histories that could never contradict each other because
they never met.

**Values.** `"Safehouse"`, `"safehouse"` and `{"value": "safehouse"}` compared
unequal, so the gate fired on formatting. A gate that cries wolf gets turned
off, at which point it protects nothing.

`normalise_alias` reduces a name to letters and digits, case-folded, accents
stripped:

| Written | Key |
|---|---|
| `Rene O'Hara` | `reneohara` |
| `René OHara` | `reneohara` |
| `rene o hara` | `reneohara` |
| `Mira-Kisaragi` | `mirakisaragi` |
| `Mira Kisaragi` | `mirakisaragi` |

Separators are removed rather than normalised to a space. That is the only rule
under which all three spellings of `Rene O'Hara` agree — keep a separator and
two of the three disagree with the third. The cost is that `"Red Sun"` and
`"Redsun"` collide; for character names that is almost always right, and where
it is wrong the unique constraint surfaces it as a refused write rather than a
silent merge.

`normalise_fact_value` unwraps single-key scalar wrappers, folds case,
collapses whitespace, treats `3` and `3.0` as one quantity, and sorts lists
(a reordered trait list is the same trait list). It returns `None` — meaning
*no canonical form* — for structures too rich to flatten, and callers then fall
back to raw equality. That fallback is **stricter**, not looser: the failure
mode is a reported difference a human dismisses, never a missed contradiction.

One sharp edge, handled: `None` normalises to a sentinel, not to the text
`"null"`, so an absent value never compares equal to a fact whose value is
literally the string `null`.

## 2. Entity aliases — ambiguity refused, not detected

`canonical_entities.aliases` was a JSON list. Two entities could both claim
`"Kisaragi"` and nothing stopped it; the clash surfaced later, at read time, in
a resolver that had to refuse.

`entity_aliases` is a table with `UNIQUE (series_id, alias_normalised)`. The
second claim now fails **at the moment someone can still fix it**, and
resolution is one indexed lookup instead of a scan over every entity.

The registry writes the entity code, the display name and every alias into the
index. `POST /canon/aliases` adds more later. `CanonicalEntity.aliases` stays as
the display list, with `EntityRegistry` the only writer of either.

Migration `0006` backfills the table from the existing JSON. A pre-existing
cross-entity clash records the first claim and skips the second rather than
failing the migration — a state an operator can see and fix, where a failed
migration on a production database is not.

### Fuzzy matching is a suggestion, never a resolution

`resolve()` is exact-only. `suggest()` is the fuzzy half — `SequenceMatcher`
over normalised aliases, threshold `0.82`, best match per entity — and nothing
in the pipeline acts on it.

This is a deliberate departure from the "fuzzy alias matching" the spec asked
for. A 0.9 similarity that is *wrong* attaches a fact to the wrong character,
and nothing afterwards reveals it: the fact simply never contradicts anything
again. Silent corruption of canon is strictly worse than not resolving. So a
near miss is surfaced — in the contradiction result as `entity_suggestions`, and
at `GET /canon/entities/{series}/suggest` — and a person decides.

## 3. Fact versioning

New columns on `memory_facts`:

| Column | Purpose |
|---|---|
| `normalised_value` | canonical comparison form (`NULL` ⇒ compare raw) |
| `timeline_start_order` / `timeline_end_order` | denormalised timeline positions, so the matcher orders facts without a query each |
| `supersedes_fact_id` | what this fact replaced |
| `is_retcon` | set **only** by an approved retcon |
| `retcon_group_code` | groups every fact one approval wrote |
| `confidence_score` | 0.0–1.0, feeds severity |
| `source_priority` | higher wins; approved retcons outrank agent writeback |

`is_retcon` is derived, never caller-set. A self-declared retcon would let any
draft opt out of the check it exists to face — the same loophole the
stored-fact-governs rule closes for `mutability`.

The denormalised orders are the one place drift is possible, so `TimelineService`
owns them: `create_event` and `rebalance` both call `resync_fact_orders`, and
a benchmark case asserts a retcon is still caught after a rebalance.

## 4. Timeline rebalancing

Insert three events between 4 and 5 and the next insertion has nowhere to go.
`POST /canon/timeline/rebalance` respaces to `gap, 2·gap, …` preserving order.

Two passes, not one: `(series_id, order_index)` is unique, so writing the new
values directly collides with rows still holding them. The first pass parks
every row at a negative index no real row can occupy.

## 5. Retcon approval workflow

Shows revise their own past on purpose. A gate with no legitimate way through
is a gate people route around.

```
draft rewrites settled canon
        │
        ▼
  contradiction (blocking)          ← unchanged
        │
        ▼
  POST /canon/retcons               ← files a request; unblocks nothing
        │
        ▼
  POST /canon/retcons/{code}/approve   requires decided_by
        │
        ├── old fact → status "superseded", valid_to set   (kept, not deleted)
        ├── new fact → is_retcon, supersedes_fact_id, group code, priority 200
        └── matching contradictions → resolved, non-blocking, attributed
```

Three properties the tests pin:

- **Filing is not deciding.** A pending proposal blocks exactly as before.
- **An approval is value-specific.** It covers `"the Alley"` written as
  `"THE ALLEY"` — matched through normalisation, or every capitalisation would
  need its own approval — and does **not** cover `"rooftop"`, or any other fact
  in the same draft.
- **The old fact survives.** "What was true before the rewrite" stays
  answerable, which is the difference between a recorded retcon and a lie.

## 6. Causality

Chronology says which event is earlier. It cannot say the ritual that sealed
the gate happens *after* the gate is already sealed.

`timeline_causal_links` records `cause → effect` edges (`causes`, `enables`,
`prevents`). `GET /canon/causal-check/{series}` reports two impossibilities:

- **`effect_before_cause`** — the effect sits at or before its cause.
  `prevents` is exempt: it asserts the effect does *not* follow, so the
  ordering rule for `causes` would flag every one of them.
- **`causal_cycle`** — a loop with no first link, which no renumbering can fix,
  so it is reported as its own kind of problem rather than as an ordering error.

The publish gate checks causality **series-wide but gates episode-scoped**: a
loop between two EP07 events holds EP07, not every other episode. Holding
everything for one episode's problem is how a check becomes something people
route around.

## 7. Severity scoring

`severity` was always `"high"`, which sorts a queue of forty findings no better
than random. `severity_score` (0–100) is computed from:

| Input | Effect |
|---|---|
| immutable change vs retcon | base 60 vs 45 — nothing downstream absorbs an immutable rewrite |
| fact `importance` | `critical` +20 … `low` −10 |
| authority gap | +10 when the draft contradicts higher-priority canon |
| lower confidence of the two | up to −20 — a hedged claim is a smaller problem |
| retcon reach | up to +15 — four episodes back invalidates more than one scene |

`severity_band()` maps the score to `critical / high / medium / low`. The
weights are a reviewable guess, not a measurement; what the tests pin is the
**ordering** they produce.

## 8. The adversarial suite

`POST /evaluation/runs` runs 18 cases against the live deployment;
`GET /evaluation/suite` describes them without running them;
`GET /evaluation/runs/{code}/report` renders failures grouped by category.

Every gate has two failure modes and only one is visible. Blocking something it
should have passed generates a complaint. **Passing something it should have
blocked generates nothing at all** — it looks exactly like a gate with nothing
to catch. The suite exists for the second one.

Half the cases assert nothing fires. That is not padding: a matcher that blocks
every fact change scores 100% on a suite made only of real contradictions and
would be unusable in production. Results are reported split:

```
Catches real problems: 10/10.  Leaves everything else alone: 8/8.
```

| Category | Cases |
|---|---|
| `entity_resolution` | alias spellings still contradict; accents and punctuation are spelling; a typo suggests but never merges; an alias clash is refused at write |
| `value_normalisation` | case and whitespace; wrapped vs bare scalar; reordered list |
| `mutability` | immutable change blocks; stateful progression passes; a self-declared `stateful` cannot override stored `immutable` |
| `timeline` | retcon blocks; rebalance preserves order and resyncs facts; retcon survives a rebalance |
| `retcon` | an approved retcon rewrites canon and passes; an approval does not unblock other facts |
| `causality` | effect before cause; causal cycle; a correct chain is quiet |

Each case builds its own series inside a savepoint that is always rolled back.
Cases that share state contaminate each other — a contradiction left by one
changes the verdict of the next — and a case failing with a database error
would otherwise poison the session and turn one failure into a suite-wide
outage that hides everything else.

Two real bugs were found this way while building it, both invisible to the
existing tests: `EntityRegistry.create` inserting `"KADE"` and `"Kade"` as two
rows (autoflush is off, so its own duplicate check could not see the pending
row), and `normalise_alias` making `"Rene O'Hara"` and `"René OHara"` different
people.

## 9. Testing against Postgres

`tests/test_postgres_integration.py` covers what SQLite cannot: that the
migration chain builds the schema the models expect, that JSON columns are
JSONB and UUIDs native, that the alias and timeline unique constraints are
enforced *by the database* and not only by the service, that rebalancing does
not trip the unique constraint under a strict dialect, and that
`SELECT … FOR UPDATE` actually locks.

It needs a Postgres, and gets one from either:

```bash
# an explicit throwaway database
export ANIME_TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/anime_test

# or testcontainers, with a Docker daemon running
pip install -e '.[postgres-tests]'
```

With neither, these tests **skip** — they never fail for want of a database.
The SQLite suite still covers the logic, and turning an absent daemon into a
red build teaches everyone to ignore red builds.

> **Not verified here.** This environment has no Docker daemon and no Postgres,
> so only the skip path has been exercised. The assertions are written against
> the documented behaviour of the dialect; they have not been observed passing.
> The SQLite suite (251 tests) and the migration round-trip have been.

---

## Endpoint summary

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/canon/aliases` | teach the registry another spelling |
| `GET` | `/canon/entities/{series}/suggest?name=` | near misses, for a human |
| `POST` | `/canon/timeline/rebalance` | respace order indexes |
| `POST` | `/canon/causal-links` | record a cause → effect edge |
| `GET` | `/canon/causal-check/{series}` | causal impossibilities |
| `POST` | `/canon/retcons` | file a rewrite request |
| `GET` | `/canon/retcons/{series}` | list, filterable by status |
| `POST` | `/canon/retcons/{code}/approve` | approve, attributed |
| `POST` | `/canon/retcons/{code}/reject` | reject, attributed |
| `POST` | `/evaluation/runs` | run the adversarial suite |
| `GET` | `/evaluation/runs/{code}` | a run and its cases |
| `GET` | `/evaluation/runs/{code}/report` | grouped failure report |
| `GET` | `/evaluation/suite` | describe the suite |
