# Admin Console

Next.js 14 (App Router) front end for the anime pipeline backend. Dark cinematic
glassmorphism, with four motion pieces that each visualise real data: a floating
node graph of the pipeline, a stage conveyor, holographic queue rings, and an
isometric system map.

## Run it

```bash
npm install
cp .env.example .env.local        # point at the backend BEFORE building
npm run build
npm run start                     # http://localhost:3001
```

`NEXT_PUBLIC_API_BASE_URL` is inlined by `next build`. Changing it and
restarting does nothing — rebuild.

The backend must allow this origin. `localhost` and `127.0.0.1` are distinct
origins to a browser, so allow both:

```bash
export ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001"
```

## Checks

```bash
npm run typecheck
npm run build

API_EMAIL=you@example.com API_PASSWORD=... SHOTS=./shots npm run smoke
```

`smoke.mjs` drives the real UI with Playwright: signs in, walks every
authenticated page, previews a canon-bound prompt, runs the adversarial suite,
and fails on any console error. It exists because the unit tests mock the API —
running it against a populated database is what caught a cross-series canon leak
that isolated fixtures had hidden.

## Layout

```
app/          one directory per route, all client components
components/
  motion/     pipeline-graph, conveyor, holo-rings, system-map
  shell/      nav, auth guard, signed-in identity
  ui/         cards, pills, tables, buttons
hooks/        useApi, usePolling (pauses when the tab is hidden)
lib/          typed API client, auth storage, shared types
```

Full write-up: [`docs/anime-pipeline/10-admin-console.md`](../docs/anime-pipeline/10-admin-console.md).
