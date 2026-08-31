# Generation Integration

Seven documents describe a system that knows what is true about a series and
refuses changes that contradict it. None of them generate anything. This layer
wires real model providers in — and, more importantly, decides *which direction*
canon and generation talk to each other.

Implementation: `app/services/generation/providers/`,
`app/services/generation/prompts/`, `dispatch.py`, `job_handlers.py`,
`app/api/routes/generation.py`.

---

## 1. Canon constrains generation before the call, not after

This is the design decision the rest of the layer follows from.

The obvious wiring is: generate a script, run it through the contradiction gate,
reject it if it breaks canon. That wastes the call, and it is worse than
wasteful — a rejected draft that a human already likes creates pressure to
approve it anyway, which is precisely how canon drifts.

So `CanonPromptBuilder` renders established facts *into* the prompt:

```
ESTABLISHED CANON — every one of these is already true and may not be contradicted:
- Mira Kisaragi.species = 'human' (fixed)
- Mira Kisaragi.location = 'safehouse' (as of now)
```

`(fixed)` marks an immutable fact; `(as of now)` marks one that may legitimately
change. The distinction has to reach the model, because "Mira is human" and
"Mira is in the safehouse" are not equally negotiable, and a model given a flat
list of facts treats them as equally so.

The gates still run afterwards. They are now a backstop rather than the primary
mechanism.

### Ordering is not cosmetic

Facts are ordered by importance, then entity. The comment in the source says
why:

> Ordered by importance then entity so the block is stable between calls — an
> unstable prefix would defeat prompt caching on every request.

Canon is the longest and most repeated part of every prompt for a series. If its
order varies run to run, the cached prefix never matches and every call pays
full input price.

At most 120 facts are rendered. Past that the canon block crowds out the actual
brief. Because the list is ranked, the cut lands at the bottom rather than
arbitrarily.

### Empty canon says so

A series with no facts yet does not get an empty block — it gets an explicit
warning that anything the model invents becomes binding once approved. Silence
would read as "no constraints", which is the opposite of the truth for episode
one.

## 2. Templates fail loudly

Eight templates (`episode_script_v1`, `episode_outline_v1`, `shot_prompt_v1`,
`narration_prompt_v1`, `bgm_prompt_v1`, `thumbnail_prompt_v1`,
`hook_variations_v1`, `continuity_review_v1`), each with a declared variable
list.

A missing variable raises `MissingTemplateVariableError`. It does not render
`{style_rules}` into the prompt. A leaked placeholder produces a plausible
response built on a literal brace-wrapped token, and nothing downstream can tell
that from a real answer.

The shared system prompt, `CANON_DISCIPLINE`, states the rule the whole
continuity system rests on: never state a world-fact that was not in the canon
block; if something is unknown, write around it or say so.

## 3. Providers

| Provider | Transport | Why |
|---|---|---|
| `mock` | none | Deterministic. Makes the whole pipeline testable and demonstrable with no key and no spend |
| `anthropic` | official SDK | One vendor, one SDK: typed errors, retries and streaming already correct |
| `openai_compatible` | raw HTTP | A *wire format*, not a vendor — vLLM, Ollama, Groq, Together all speak it. An SDK here would pin one vendor's client to a format many implement |

The asymmetry is deliberate, and it is the one thing about this module that
looks like an inconsistency until you know the reason.

### The Anthropic adapter

```python
DEFAULT_MODEL = "claude-opus-5"
request = {"model": model_id, "max_tokens": max_tokens,
           "messages": [...], "output_config": {"effort": effort}}
if thinking:
    request["thinking"] = {"type": "adaptive"}
if max_tokens > 16_000:
    with client.messages.stream(**request) as stream:
        message = stream.get_final_message()
```

Three details that are easy to get wrong:

- **`thinking` is `{"type": "adaptive"}`.** The older `budget_tokens` form is
  rejected with a 400 on current models.
- **Large `max_tokens` must stream.** A non-streaming request for a long
  response hits the request timeout before the response finishes.
- **A refusal arrives as HTTP 200.** `stop_reason == "refusal"` is checked
  explicitly; treating only exceptions as failures would store a refusal as if
  it were a script.

SDK exceptions are translated into two classes: `ProviderCallError` (retryable —
rate limits, timeouts, 5xx) and `ProviderNotConfiguredError` (terminal — no key,
bad key, unknown model). The queue's retry budget only means something if the
distinction is made at the boundary.

## 4. Provider resolution happens before enqueueing

`POST /generation/run` resolves the provider *first*, then enqueues.

If it enqueued first, a missing API key would become a job that wakes up three
times over twelve minutes, fails identically each time, and reports at 3am. As
written it is a 400 on the request, while the person who typed it is still
looking at the screen.

## 5. Provenance

Every completed generation writes an `Artifact` recording the provider, the
model id, the template key and the correlation id of the request that started
it.

Six months on, "which model wrote this scene, under which prompt version" is a
question someone will ask — after a regression, or when a template changes and
the earlier output needs re-reading in its own context. It is unanswerable
unless it was recorded at the time.

The `artifact_code` carries a random suffix, so regenerating produces a *new*
artifact rather than overwriting the previous one. The old output is evidence.

## 6. Media providers

Text generation returns in seconds. Media generation takes minutes and costs
real money per call, and those two facts shape the whole interface.

`MediaProvider` therefore exposes **`submit` and `poll` as separate
operations** rather than one blocking `generate`. A blocking call would hold a
worker for the duration of a video render and lose the generation entirely if
the process restarted — after it had already been paid for. The job queue drives
the wait across separate transactions instead.

`MediaResult.cost_usd` exists for the same reason. "What did this episode cost
to make" is a question someone will ask, and it is unanswerable unless every
call records its own price at the time. An unreported cost is `None`, never
`0.0` — "not reported" and "free" are different facts, and flattening them makes
a cost report quietly wrong.

### MuAPI

`app/services/generation/providers/muapi.py`. One endpoint in front of many
image, video and audio models:

```
POST https://api.muapi.ai/api/v1/{model}     -> {"request_id": …}
GET  https://api.muapi.ai/api/v1/predictions/{request_id}/result
                                             -> {"status", "outputs", "cost"}
```

with `x-api-key` on both. Raw HTTP, for the same reason as the
OpenAI-compatible adapter: a small stable REST surface, not a vendor whose SDK
carries behaviour worth inheriting.

Four decisions worth knowing:

**The model is a URL path segment.** `flux-schnell-image`,
`openai-sora-2-text-to-video`. That puts caller-supplied text into a URL, so
model names are validated against a strict allowlist rather than escaped — an
allowlist cannot be got wrong the way escaping can. A model string carrying
`../` would otherwise reach an endpoint nobody named.

**Failure is terminal, not retryable.** A retry re-runs a *paid* generation, and
a job the service rejected usually fails again for the same reason. The budget
is better spent on a human reading the error and changing the prompt. Insufficient
credit (402) and a rejected key (401/403) are terminal for the same reason. Rate
limits (429) and 5xx are retryable, because those genuinely do pass.

**An unrecognised status means pending, never success.** Guessing "done" from a
word the adapter has not seen would hand the caller an empty output list dressed
as a finished generation. A `completed` with no outputs is likewise an error
rather than an empty success.

**Network failures are caught narrowly.** A blanket `except Exception` around the
HTTP call would catch a `TypeError` in the adapter and report it as an
unreachable host — which the queue treats as *retryable*, so a programming error
would quietly burn its retry budget three times instead of failing loudly once.

### Testing it

`tests/test_media_providers.py` pins the behaviour against a fake transport and
reaches nothing. The live check is `scripts/muapi_live_check.py`, deliberately
**not** a pytest test: it needs a key and spends money, and a test suite that
sometimes bills you is one people stop running.

```bash
export MUAPI_API_KEY=...          # never in a config row, never committed
python scripts/muapi_live_check.py --prompt "a lighthouse at dusk"
```

The key belongs in the environment, not in a workspace config profile — which is
why `PUT /workspaces/{slug}/config-profiles` refuses keys that look like
credentials (§7 of document 08).

---

## Endpoints

| Route | Purpose |
|---|---|
| `GET /generation/templates` | Templates and their required variables |
| `GET /generation/providers` | Text and media providers, each with its default model and whether it is configured |
| `POST /generation/preview` | Render the real prompt, canon block and all, without spending a token |
| `POST /generation/run` | Resolve the provider, enqueue the call |

`POST /generation/preview` is the endpoint worth pointing at. Prompt bugs are
expensive to find by inspecting outputs and cheap to find by reading the prompt.

Text and media are listed separately by `GET /generation/providers`, because
they are chosen separately: a deployment can run a real LLM behind a mock image
generator, and one merged list would hide that.

## Configuration

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Enables the `anthropic` text provider |
| `ANIME_ANTHROPIC_MODEL` | Overrides the default model id |
| `ANIME_OPENAI_BASE_URL` · `ANIME_OPENAI_API_KEY` · `ANIME_OPENAI_MODEL` | Any OpenAI-compatible endpoint |
| `MUAPI_API_KEY` | Enables the `muapi` media provider |
| `ANIME_MUAPI_MODEL` | Default endpoint/model slug (e.g. `flux-schnell-image`) |
| `ANIME_MUAPI_BASE_URL` | Overrides the API base |

With none of these set, `mock` is the only ready provider on both sides and
everything still runs end to end.
