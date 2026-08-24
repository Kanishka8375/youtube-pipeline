# Access Control and Deferred Work

Everything before this layer assumed one trusted caller and one process. Both
assumptions break the moment the pipeline runs for real: several people share a
show, and a generation call takes minutes rather than milliseconds.

This layer adds identity, workspaces with an ordered role ladder, a durable job
queue, correlation ids that survive the hop from request to worker, and an audit
log for the decisions that matter.

Implementation: `app/core/security.py`, `app/core/config.py`,
`app/core/request_context.py`, `app/core/logging.py`,
`app/api/middleware/correlation.py`, `app/api/deps.py`,
`app/services/auth/`, `app/services/workspaces/`, `app/services/jobs/`,
`app/services/audit/`. Migration `0008`.

---

## 1. Passwords

`pbkdf2_sha256$200000$<salt>$<digest>` — algorithm, iteration count, salt and
digest in one string.

The iteration count travels *with the hash* rather than living in a constant.
That is the whole point of the format. Raising the work factor in a constant
would invalidate every stored hash and lock out every user; storing it per-hash
means a raised factor applies to new and re-entered passwords while old ones
keep verifying at the factor they were written with.

Comparison is `hmac.compare_digest`, not `==`. A short-circuiting comparison
leaks the length of the matching prefix through timing.

## 2. Tokens

`TokenSigner.decode` never consults the token's own `alg` header.

That sentence is the entire security property. A decoder that reads `alg` from
the token and then verifies with that algorithm can be handed `alg: none` and
will happily accept an unsigned token; hand it `alg: HS256` against a service
that signs with RS256 and the public key becomes the HMAC secret. The header is
attacker-controlled input, so it is treated as decoration:

```python
expected = self._sign(f"{header_b64}.{body_b64}".encode())
if not hmac.compare_digest(expected, provided):
    raise InvalidTokenError("Bad token signature")
```

A token with no `exp`, or an `exp` that is not an integer, is rejected rather
than treated as non-expiring. "Missing" must not mean "forever".

Every failure path — malformed, bad signature, expired, unknown subject —
raises the same `InvalidTokenError` and surfaces as the same 401 with the same
body. Telling a forger *which half* of the token was wrong tells them which half
to keep working on.

## 3. The signing key cannot be forgotten into production

The default secret is a literal named `INSECURE_DEV_SECRET`, so it is obvious in
a config dump. `require_production_secret()` runs in the FastAPI lifespan and
raises when `ANIME_ENV` names a real deployment and the key is still the
default.

A hard startup crash, not a warning. A default that works everywhere is exactly
the kind that survives into production, and a warning in a log is not a control.

## 4. Account enumeration

`POST /auth/login` returns an identical status *and body* for a wrong password
and an unknown address. Different responses turn the login form into a free
membership oracle for any address someone cares to test.

## 5. Workspaces: 404, not 403

A workspace the caller is not a member of returns **404**, the same as one that
does not exist.

A 403 would confirm the slug is real. For a private show that is the leak: an
outsider enumerating slugs learns which projects exist. Once membership *is*
established, an insufficient role returns 403 — the caller already knows the
workspace exists, and a 404 there would be actively confusing.

## 6. The role ladder

```
owner (4) > editor (3) > member (2) > viewer (1)
```

Roles are ordered, not a set of flags, so `require_role("editor")` admits owners
without enumerating them. An unrecognised role ranks **0** and therefore fails
every check — a typo in a database row denies access rather than granting it.

## 7. Config profiles refuse to store secrets

`PUT /workspaces/{slug}/config-profiles` rejects any key that looks like a
credential. Provider settings belong in a workspace profile; provider *keys* do
not — a database row is read by more people, backed up to more places, and
audited less than an environment variable.

The filter matches whole underscore-separated words, not substrings, and carries
an allowlist:

```python
_SECRET_WORDS = {"key", "keys", "secret", "token", "tokens", "password", ...}
_SECRET_ALLOWLIST = {"provider_key", "model_key", "max_tokens", "input_tokens", ...}
```

Both refinements came from false positives. Substring matching rejected
`provider_key` — the one setting the endpoint exists to store. And `max_tokens`
means an LLM billing unit here, not a credential. A filter that blocks
legitimate configuration gets disabled, at which point it protects nothing.

## 8. The job queue

`background_jobs` is a table, not a broker. That is a deliberate trade: one
fewer piece of infrastructure, transactional consistency with the domain data
the job is about, and a queue you can inspect with SQL.

Claiming is `SELECT ... FOR UPDATE SKIP LOCKED` on the databases that support it
(Postgres, MySQL, Oracle) so two workers never take the same row and neither
blocks the other. SQLite has no row locks, so it falls back to a plain select —
correct for the single-worker development case, which is the only case SQLite is
for.

Retries back off `30s → 120s → 600s`, then the job is terminal.

### The bug worth documenting

The attempt counter is committed *before* the handler runs:

```python
def _mark_running(self, job):
    job.status = RUNNING
    job.attempt_count += 1
    job.started_at = _now()
    self.session.commit()      # committed, not flushed
```

A handler that fails leaves the session dirty, so `execute` must roll back
before it can record the failure. That rollback would also undo an
*uncommitted* increment. The attempt count would reset on every failure, the
retry budget would never deplete, and a permanently broken job would retry
forever at ten-minute intervals until someone noticed the bill.

Committing the claim first makes the attempt durable regardless of what the
handler does to the transaction.

`execute()` also calls `_mark_running` itself when the job is not already
`running`. Two entry points reach the same invariant — `claim_next()` for the
worker loop, `execute()` for a direct call — and an invariant enforced in only
one of them is not enforced.

### Terminal vs retryable

A handler raising `TerminalJobError` is not retried. Malformed input does not
become well-formed on the third attempt; retrying it just spends the budget
before a real transient failure can use it.

## 9. Correlation ids

`CorrelationIdMiddleware` reads or mints an id per request, stores it in a
`ContextVar`, echoes it as `X-Correlation-ID`, and the logging filter stamps it
onto every line. Enqueued jobs record the id of the request that created them.

So one identifier spans HTTP request → queued job → the log lines of a worker
that ran minutes later in another process. Without it, "why did this episode
fail" means correlating by timestamp across two processes, which works until two
requests arrive in the same second.

## 10. The audit log

Membership grants, role changes and retcon approvals write an `AuditEvent`
naming the actor, the action, the target and the time. These are the decisions
someone will later need to reconstruct — not a general-purpose event stream, and
deliberately not one, because a log that records everything is one nobody reads.

---

## Endpoints

| Route | Purpose |
|---|---|
| `POST /auth/register` · `/auth/login` · `GET /auth/me` | Identity |
| `POST /workspaces` · `GET /workspaces` | Create and list your workspaces |
| `GET /workspaces/{slug}` · `/members` · `POST /members` | Membership |
| `GET /workspaces/{slug}/audit-log` | Who decided what |
| `PUT` · `GET /workspaces/{slug}/config-profiles` | Per-workspace settings, secrets refused |
| `POST /jobs` · `GET /jobs` · `GET /jobs/{id}` | Enqueue and inspect |
| `GET /jobs/handlers` · `POST /jobs/drain` | What can run; run it now |
| `GET /system/health` · `/system/readiness` | Liveness, and whether dependencies answer |

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `ANIME_SECRET_KEY` | insecure dev default | Signs bearer tokens. Required when `ANIME_ENV` is production |
| `ANIME_ENV` | `local` | `production`/`prod`/`staging` enable the startup secret check |
| `ANIME_TOKEN_TTL_MINUTES` | `1440` | Token lifetime |
| `ANIME_CORS_ORIGINS` | `http://localhost:3001` | Comma-separated admin UI origins |
| `ANIME_STORAGE_PROVIDER` | `local` | Where generated media lands |
| `ANIME_STORAGE_ROOT` | `./storage` | Root for the local provider |
