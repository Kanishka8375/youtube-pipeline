# Canon Memory

The layer that stops drift. Every agent reads it before working; approved
output writes back into it. Without it, episode 12 forgets who episode 3 said
Mira was.

Implementation: `anime_pipeline/app/services/memory_service.py`,
`anime_pipeline/app/services/consistency_guard.py`.

---

## Four scopes

| Scope | `memory_type` | Holds |
|---|---|---|
| Series | `series_canon`, `style_memory` | World rules, lore, naming, visual and sound identity |
| Season | `season_memory` | Season themes, arc, recurring symbols, pacing profile |
| Episode | `episode_memory` | Approved brief, new canon, unresolved hooks |
| — | `character_profiles`, `style_bibles` | First-class tables, not documents |

`memory_type` and scope are validated together: a `series_canon` document
cannot claim an episode scope. `scope_id` is polymorphic (series, season or
episode), so the database cannot enforce it with a foreign key — the service
layer does, on write.

## Documents vs facts

**Documents** hold prose an agent reads. **Facts** hold something the system
can look up and compare — one entity, one key, one value.

Facts are never deleted. A replacement supersedes its predecessor by setting
`status = superseded` and `valid_to_episode_id`, so "what was true at EP04"
stays answerable. That property is the whole point: a canon store that
overwrites cannot answer questions about the past, which is most of what
continuity work asks.

## The consistency guard

`POST /memory/consistency-check` audits a draft script against canon.

**What it checks mechanically:**

| Check | Fires when |
|---|---|
| `forbidden_phrase` | A character says a literal phrase canon forbids |
| `line_too_long` | A line exceeds the character's `max_line_words` |
| `monologue` | Consecutive lines exceed `max_consecutive_lines` |
| `banned_term` | A scene uses terminology the style bible bans |

**What it deliberately does not check.** Rules like *"never becomes bubbly
comic relief"* are prose. A substring search for that sentence against dialogue
can never match a real line, so a guard built that way passes everything and
reports success — worse than no guard, because it manufactures confidence.
Those rules go to `not_mechanically_checked` and reach the Master QC agent,
whose job is judgement.

**A pass therefore means "nothing mechanically checkable failed", not "this is
consistent".** The response says so explicitly, and so does the stored
continuity record.

### `speech_style` keys

Mechanically checked:

```json
{
  "forbidden_phrases": ["totally", "you got this"],
  "max_line_words": 12,
  "max_consecutive_lines": 2
}
```

Reviewer-only — carried, never auto-passed: `tone`, `patterns`,
`notes_for_reviewer`, and anything else.

### Speaker resolution

Scripts credit speakers the way a reader would ("Mira", "Mira Kisaragi"); canon
keys them by code ("MIRA"). The resolver indexes code, display name, aliases
and the display name's first token, case-insensitively. Matching on code alone
resolves almost nothing, which would silently check no dialogue at all.
Unresolved speakers are reported in `unknown_speakers` rather than skipped.

## Writeback

`POST /memory/writeback` folds an approved artifact into canon.

The parser **refuses rather than guesses**. A fact missing required keys, a
state change naming an unknown character, a hook with no code — each goes to
`deferred` with a reason, for the showrunner to resolve. Nothing is dropped and
nothing is approximated: a wrong fact written into canon propagates into every
later episode.

A character state change updates the profile *and* records a
`character_state` fact carrying `{previous, patch, result}`. The profile holds
the present; the fact holds the change.

## What each agent should read

| Agent | Needs |
|---|---|
| Executive Showrunner | Series canon, season memory, style bible |
| Season Planner | Season arc, unresolved hooks |
| Episode Story | Season arc, previous episode summaries, hooks, characters |
| Scriptwriting | Character profiles, dialogue rules, canon facts, pacing |
| Continuity | Everything approved, timeline, character state |
| Character Asset | Character profiles, `do_not_change`, visual design |
| Background & Props | Location and prop memory, visual rules |
| Storyboard | Style bible, cinematography and pacing rules |
| Edit & Motion | Style bible editing rules, frame rate, approved cut logic |
| Packaging | Title, thumbnail and hook pattern memory |
| Master Anime QC | All of the above, plus prior QC issues for drift detection |

One call: `GET /memory/bundles/agent/{agent_code}?episode_code=EP01`.

The bundle carries `provenance` — the memory codes and versions it was built
from. Record it on the task so a later question about why an agent wrote
something has an answer.

## Publish gate

Continuity is now part of the existing gate rather than a second one beside it:

```
GET /qc-reports/episode/{code}/publish-gate
```

Four checks, all required:

| Check | Passes when |
|---|---|
| `qc_score_ok` | Final-cut `overall_score` ≥ `PUBLISH_SCORE_THRESHOLD` (85) |
| `mandatory_fixes_closed` | No outstanding `required_fixes_before_publish` |
| `no_critical_issues` | No `critical_issues` |
| `continuity_passed` | A passing continuity check exists for the episode |

The threshold lives in exactly one constant,
`app/schemas/master_qc_report.py`. A second gate service carrying its own
`qc_threshold=85` would put the number in a fourth place, which is the drift
the single constant exists to prevent.

`publish_ready` is recomputed from the report's sections on every read, never
taken from the stored column — see
[02-qc-framework.md](02-qc-framework.md#what-was-inconsistent-in-the-original-design).

## Testing against real Postgres

The suite runs against SQLite by default: the models use
`JSON().with_variant(JSONB, "postgresql")` and `sa.Uuid`, so one model set
serves both, and the tests need no infrastructure.

That is not the same as testing against Postgres. To do that, point the suite
at a real database:

```bash
export ANIME_DATABASE_URL=postgresql+psycopg://user:pass@localhost/anime_test
alembic upgrade head
pytest
```

A `testcontainers`-based fixture would automate this, but it needs a Docker
daemon. None was available where this was built, so shipping that config
unverified would be a guess — run the command above, or add the fixture once
you have Docker in CI.
