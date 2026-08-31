# Admin Console

A Next.js 14 App Router front end for the backend described in documents 01–09.
Dark cinematic glassmorphism, with four pieces of motion that each visualise a
real data structure rather than decorating an empty one.

Implementation: `frontend/`.

---

## 1. The motion visualises real data, or it is a lie

This is the constraint the whole visual layer is built under.

**The floating node graph** lays out the actual fifteen stages from
`GET /pipeline/stages`, positioned by *computed dependency depth*:

```ts
const value = !stage?.depends_on.length
  ? 0
  : 1 + Math.max(...stage.depends_on.map((d) => depth(d, seen)));
```

So the picture shows the real shape of the graph — what can run in parallel,
where the gates are, which stage is the bottleneck. A prettier arbitrary
arrangement would look better and tell you nothing, and worse, would tell you
something false.

The same rule governs the other three: the **conveyor** shows per-stage progress
for the selected episode, the **holographic rings** show live queue depth from
`GET /jobs`, and the **isometric system map** shows which subsystems are actually
reachable from `GET /system/readiness`. Nothing animates that is not measuring
something.

The depth walk carries a `seen` set and returns 0 on a revisit. A cycle would
otherwise recurse forever and hang the browser. The API validates the pipeline
against cycles at import — but a client that hangs when the server is wrong is
still a client that hangs.

## 2. Accessibility is not a separate pass

Status is never carried by hue alone. Every state pill pairs a colour with a
*word* (`queued`, `completed`, `failed`), and the colours differ in lightness as
well as hue, so they remain distinguishable in greyscale and to a red–green
colourblind reader. On a screen whose entire job is "did this fail", a bare red
dot is not an answer.

All four motion pieces honour `prefers-reduced-motion` and settle into their
final positions rather than animating.

## 3. Polling stops when the tab is hidden

`usePolling` checks `document.visibilityState` and skips the request when the tab
is in the background. A dashboard left open in a tab for a working day would
otherwise issue thousands of requests nobody is looking at.

`useApi` guards writes behind an `alive` ref, so a slow response from a page the
user has already left cannot write into an unmounted component.

## 4. The login form posts

```tsx
<form method="post" onSubmit={...}>
```

The `method="post"` is not decoration. Without it, a JavaScript chunk that fails
to load leaves a native form that submits as **GET** — and the password lands in
the URL, in browser history, and in every access log between here and the
server. This was observed, not theorised: a 400 on the JS chunks during
development produced exactly that URL.

Tokens live in `localStorage`, which is the right trade for an internal admin
console; a `Secure; HttpOnly` cookie would be better and needs a same-site
deployment to be worth the complexity.

## 5. `NEXT_PUBLIC_*` is inlined at build time

`NEXT_PUBLIC_API_BASE_URL` is baked into the bundle by `next build`. Changing
the environment and restarting does nothing — the old value is already in the
JavaScript. Set it *before* building, and rebuild when it changes.

## 6. The smoke script

`npm run smoke` drives the real UI against a live backend with Playwright: signs
in, walks all six authenticated pages, previews a canon-bound prompt, runs the
adversarial suite from the evaluation page, and fails on any console error.

It earns its place. The unit tests mock the API; this script, run against a
*populated* database, found a cross-series canon leak that isolated fixtures had
hidden for four pull requests — `_active_facts` queried `MemoryFact` with no
series filter, so two shows that both had a character called MIRA contaminated
each other. pytest scored 18/18. The UI scored 16/18. The fix is
`app/services/series_scope.py`, and the regression test was confirmed to fail
against the pre-fix code before it was kept.

---

## Pages

| Route | What it is for |
|---|---|
| `/login` | Sign in |
| `/dashboard` | Queue depth, provider readiness, the pipeline graph, system map |
| `/pipeline` | The stage graph as the orchestrator holds it — dependencies and gates |
| `/jobs` | Deferred work, retry budgets, correlation ids, failure reasons |
| `/generation` | Templates, provider readiness, and prompt preview |
| `/evaluation` | Run the adversarial continuity suite and read the split |
| `/workspaces` | Members, roles, config profiles, audit log |

## Running it

```bash
cd frontend
npm install
cp .env.example .env.local        # set the backend URL before building
npm run build && npm run start    # http://localhost:3001
```

The backend must allow the console's origin:

```bash
export ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001"
```

Both spellings, because `localhost` and `127.0.0.1` are different origins to a
browser and it will happily let you spend twenty minutes discovering that.
