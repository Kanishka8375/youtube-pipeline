# YouTube Content Creation Pipeline

Tooling for running faceless YouTube channels. The repository holds **five
components that install and run independently** — you do not need all of them:

| Component | What it is | Language |
|---|---|---|
| [Video pipeline](#2-video-pipeline-root) | Script → TTS → video → upload, on free models | Python |
| [Anime pipeline](#3-anime-pipeline-backend) | Multi-agent FastAPI backend with an enforced continuity canon | Python |
| [Admin console](#4-admin-console-frontend) | Next.js operations UI for the anime pipeline | Node |
| [ChatterBox Studio](#5-chatterbox-studio-tts) | Multi-model TTS web app | Python |
| [Desktop app / web UI](#6-desktop-app-and-web-ui) | Wrappers around the video pipeline | Python |

Pick the section you need. Each is self-contained; §1 is common to all of them.

> **New to the terminal?** This page assumes you are comfortable with one.
> [**INSTALL.md**](INSTALL.md) walks through the same installations from
> scratch — opening a terminal, installing Python, what each command does and
> what you should see when it works.

---

## 1. Prerequisites

| Tool | Version | Needed by | Check |
|---|---|---|---|
| Python | **3.11+** | everything Python | `python3 --version` |
| Node.js | **18+** (22 tested) | admin console | `node --version` |
| npm | 9+ (10 tested) | admin console | `npm --version` |
| git | any | cloning | `git --version` |

**ffmpeg is not a separate install.** `imageio-ffmpeg` (in `requirements.txt`)
bundles a binary, so MoviePy works without a system ffmpeg. If you already have
one on `PATH`, MoviePy uses it.

**Postgres is optional.** Both Python services default to SQLite and need no
database server.

### Clone

```bash
git clone https://github.com/Kanishka8375/youtube-pipeline.git
cd youtube-pipeline
```

### Use a virtualenv

The two Python components have different dependency sets. One shared venv is
fine; separate venvs are cleaner.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
```

---

## 2. Video pipeline (root)

Script generation, TTS, video assembly and YouTube upload, using free models.

### 2.1 Install

```bash
pip install -r requirements.txt
```

### 2.2 Choose an LLM provider

Pick **one**. All three are free.

**Option A — Ollama (local, no API key, unlimited)**

```bash
# Install from https://ollama.com, then:
ollama pull llama3.2
ollama serve                        # leave running; listens on :11434
```

**Option B — Groq (cloud, 8000 requests/day)**

Get a key at [groq.com](https://groq.com), then put `GROQ_API_KEY` in `.env`.

**Option C — Google Gemini (cloud, 60 requests/min)**

Get a key at [Google AI Studio](https://aistudio.google.com), then put
`GEMINI_API_KEY` in `.env`.

### 2.3 Configure

```bash
cp .env.example .env
```

Then edit `.env`:

```env
CONTENT_PROVIDER=auto              # ollama | groq | gemini | auto
OLLAMA_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434
GROQ_API_KEY=your_groq_key_here
GROQ_MODEL=llama-3.3-70b
GEMINI_API_KEY=your_gemini_key_here
GEMINI_MODEL=flash
YOUTUBE_CLIENT_SECRETS=client_secrets.json
```

`auto` picks the first provider that answers, so you can leave the unused keys
as placeholders.

Non-secret defaults (topic, duration, paths, upload behaviour, voice) live in
[`config.ini`](config.ini) and need no setup to get started.

### 2.4 YouTube credentials — only for uploading

Skip this entirely if you just want to generate videos locally.

1. Open the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project
3. Enable **YouTube Data API v3**
4. Create an **OAuth 2.0 Client ID** of type *Desktop app*
5. Download the JSON and save it to the repository root as `client_secrets.json`

The first upload opens a browser for consent and caches a token afterwards.
`client_secrets.json` is a credential — keep it out of version control.

### 2.5 Run

```bash
# Auto-detect the provider
python pipeline.py --topic "Your Video Topic" --duration 60

# Force one
CONTENT_PROVIDER=ollama python pipeline.py --topic "Your Video Topic"
```

Output lands in `output/`; `temp/` and `assets/` are created as needed.

### 2.6 Verify the provider wiring

```python
from llm_providers import LLMProviderFactory

print(LLMProviderFactory.list_available())

provider = LLMProviderFactory.create("groq")
print(provider.generate("Write a haiku about AI").content)
```

### Free model options

| Provider | Model | Limits | Best for |
|---|---|---|---|
| Ollama | llama3.2, mistral | Unlimited | Privacy, no API keys |
| Groq | llama-3.3-70b | 8000 req/day | Speed, quality |
| Gemini | gemini-1.5-flash | 60 req/min | Reliability |

TTS uses Edge TTS (free). Video assembly uses MoviePy (free).

---

## 3. Anime pipeline (backend)

A FastAPI + SQLAlchemy service for a serialized anime channel: thirteen agents,
a gated episode workflow, an enforced continuity canon, auth and workspaces, a
durable job queue, and real LLM/media providers.

### 3.1 Install

```bash
cd anime_pipeline
pip install -e ".[dev]"
```

Optional extras, each independent:

```bash
pip install -e ".[anthropic]"        # the Claude provider
pip install -e ".[postgres]"         # psycopg, for a Postgres deployment
pip install -e ".[postgres-tests]"   # testcontainers, to run the Postgres tests
pip install -e ".[dev,anthropic]"    # combine with a comma
```

Without the `anthropic` extra that provider simply reports itself unconfigured
and everything else runs on the mock.

### 3.2 Create the schema

```bash
alembic upgrade head
```

This builds all 36 tables through migration `0008` and seeds the 13 agents.
SQLite by default — no database server needed.

### 3.3 Run

```bash
uvicorn app.main:app --reload
```

Serves on `http://127.0.0.1:8000`. Interactive API docs at `/docs`.

**No API key is required.** The `mock` provider is deterministic and always
ready, so the whole pipeline — including the adversarial continuity suite —
runs end to end with nothing configured.

### 3.4 Configuration

Every variable is optional except where noted.

| Variable | Default | Purpose |
|---|---|---|
| `ANIME_DATABASE_URL` | `sqlite:///./anime_pipeline.db` | Database |
| `ANIME_ENV` | `local` | `production`/`prod`/`staging` make the secret check below fatal |
| `ANIME_SECRET_KEY` | insecure dev default | Signs bearer tokens. **Required in production** |
| `ANIME_TOKEN_TTL_MINUTES` | `1440` | Token lifetime |
| `ANIME_CORS_ORIGINS` | `http://localhost:3001` | Comma-separated admin console origins |
| `ANIME_FRAME_RATE` | `24` | Project frame rate for QC timing notes |
| `ANIME_ECHO_SQL` | unset | Log every SQL statement |
| `ANIME_LOG_LEVEL` | `INFO` | Log verbosity |
| `ANTHROPIC_API_KEY` | unset | Enables the `anthropic` text provider |
| `ANIME_ANTHROPIC_MODEL` | `claude-opus-5` | Override the model id |
| `OPENAI_COMPAT_BASE_URL` · `OPENAI_API_KEY` · `OPENAI_COMPAT_MODEL` | unset | Any OpenAI-compatible endpoint (vLLM, Ollama, Groq, Together) |
| `MUAPI_API_KEY` | unset | Enables the `muapi` image/video/audio provider |
| `ANIME_MUAPI_MODEL` | unset | Default MuAPI model slug, e.g. `flux-schnell-image` |
| `ANIME_MUAPI_BASE_URL` | `https://api.muapi.ai/api/v1` | Override the MuAPI base |
| `ANIME_STORAGE_PROVIDER` · `ANIME_STORAGE_ROOT` | `local` · `./storage` | Where generated media lands |

**The production secret check is a hard startup failure, by design.** With
`ANIME_ENV=production` and `ANIME_SECRET_KEY` still at its shipped default, the
service refuses to boot — a default that works everywhere is exactly the kind
that survives into production unnoticed. Set a real secret:

```bash
export ANIME_ENV=production
export ANIME_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

### 3.5 Postgres (optional)

```bash
pip install -e ".[postgres]"
export ANIME_DATABASE_URL="postgresql+psycopg://user:pass@localhost/anime"
alembic upgrade head
```

The models switch to native UUIDs and JSONB automatically, and the job queue
starts using `SELECT … FOR UPDATE SKIP LOCKED`.

### 3.6 Create the first account

```bash
curl -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-passphrase","full_name":"Your Name"}'
```

Note the field is `full_name`. The request model forbids unknown keys, so a
typo returns a 422 naming it rather than silently ignoring it.

Then log in for a bearer token:

```bash
curl -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-long-passphrase"}'
```

### 3.7 Verify

```bash
pytest                    # 361 passed, 10 skipped — no network or database needed
alembic check             # no un-migrated model drift
```

The 10 skips are the Postgres integration tests; they skip when no database is
available rather than failing. Install the `postgres-tests` extra, or set
`ANIME_TEST_POSTGRES_URL`, to run them.

---

## 4. Admin console (frontend)

Next.js 14 operations UI over the anime pipeline: dashboard, pipeline graph, job
queue, prompt preview, adversarial suite, workspace admin.

### 4.1 Install

```bash
cd frontend
npm install
```

### 4.2 Configure — before building

```bash
cp .env.example .env.local
```

```env
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

> **`NEXT_PUBLIC_*` is inlined at build time.** `next build` bakes the value
> into the JavaScript bundle. Changing `.env.local` and restarting does
> nothing — you must rebuild. Set it before step 4.3.

### 4.3 Build and run

```bash
npm run build
npm run start            # http://localhost:3001
```

For development with hot reload:

```bash
npm run dev              # also :3001
```

### 4.4 Let the backend accept this origin

The console is a separate origin, so the backend must allow it. Start the
backend with:

```bash
export ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001"
```

Allow **both spellings**: `localhost` and `127.0.0.1` are different origins to a
browser, and whichever one you omit is the one you will type.

### 4.5 Verify

```bash
npm run typecheck
npm run build

# End-to-end against a running backend with a registered account:
API_EMAIL=you@example.com API_PASSWORD=a-long-passphrase npm run smoke
```

`smoke.mjs` drives the real UI with Playwright — signs in, walks every
authenticated page, previews a canon-bound prompt, runs the adversarial suite —
and exits non-zero on any failed check or console error. Optional variables:
`BASE` (default `http://127.0.0.1:3001`), `SHOTS` (a directory for screenshots),
`CHROMIUM_PATH` (an existing Chromium, to skip Playwright's download).

It needs a browser. Either let Playwright fetch one:

```bash
npx playwright install chromium
```

or point `CHROMIUM_PATH` at one you already have.

---

## 5. ChatterBox Studio (TTS)

A Flask web app for multi-model text-to-speech, ComfyUI-style.

### 5.1 Install

```bash
pip install -r requirements-chatterbox.txt
```

This pulls **PyTorch (`torch`, `torchaudio` ≥ 2.6)**, which is a large download
and the slowest install in this repository. For a CUDA build rather than the
default, install torch first from [pytorch.org](https://pytorch.org/get-started/locally/),
then run the command above — pip will keep the version you already have.

### 5.2 Run

```bash
python chatterbox_app.py                        # http://localhost:5001
python chatterbox_app.py --port 8188 --auto-launch
python chatterbox_app.py --models-dir /custom/path
```

### 5.3 Add models

Drop model files into `chatterbox_studio/models/tts/<model-id>/`, then click
**⟳ Refresh Models** in the top bar (or press <kbd>R</kbd>). No restart needed.

To register model directories outside the repository, copy
`chatterbox_studio/extra_model_paths.yaml.example` to
`chatterbox_studio/extra_model_paths.yaml` and edit the paths.

---

## 6. Desktop app and web UI

Two thin wrappers around the §2 video pipeline. Both need §2 installed first.

### 6.1 Browser UI

```bash
pip install flask flask-cors        # see the note below
python web_ui.py                    # http://localhost:5000
```

> **Known packaging gap:** `web_ui.py` imports Flask, but `requirements.txt`
> does not declare it — only `requirements-chatterbox.txt` does. Install Flask
> explicitly as above, or install the ChatterBox requirements, until the
> dependency is added where it belongs.

### 6.2 Desktop app

```bash
cd desktop_app
pip install pywebview
python launcher.py
```

Or install it as a command:

```bash
pip install -e .
youtube-generator
```

See [`desktop_app/README.md`](desktop_app/README.md) for desktop shortcuts on
Linux/Windows/macOS and for building a standalone executable with PyInstaller.

`desktop-ui/` (Electron) and `tauri-app/` (Tauri) are additional shells; both
need their own toolchains (Node for Electron, Rust for Tauri).

---

## 7. Running the anime pipeline and console together

The common case — backend plus admin console, no keys, no database server:

```bash
# Terminal 1 — backend
cd anime_pipeline
pip install -e ".[dev]"
alembic upgrade head
ANIME_CORS_ORIGINS="http://localhost:3001,http://127.0.0.1:3001" \
  uvicorn app.main:app --reload

# Terminal 2 — console
cd frontend
npm install
cp .env.example .env.local
npm run build
npm run start
```

Open `http://localhost:3001`, register through the API (§3.6), and sign in.

---

## 8. Troubleshooting

**`ModuleNotFoundError: No module named 'flask'` running `web_ui.py`** — the
packaging gap in §6.1. `pip install flask flask-cors`.

**Console shows the wrong API URL** — `NEXT_PUBLIC_API_BASE_URL` was changed
after `npm run build`. Rebuild (§4.2).

**Browser console shows a CORS error** — the origin you loaded is not in
`ANIME_CORS_ORIGINS`. Add both `localhost` and `127.0.0.1` spellings (§4.4).

**Backend exits at startup with `InsecureSecretError`** — `ANIME_ENV` names a
production environment while `ANIME_SECRET_KEY` is still the shipped default.
Set a real secret (§3.4).

**`alembic upgrade head` says the database is not up to date** — you are running
from the wrong directory. `alembic.ini` lives in `anime_pipeline/`, so run it
from there.

**10 tests skip in the anime pipeline suite** — expected. They need Postgres.
See §3.7.

**`npm run smoke` cannot find a browser** — install one with
`npx playwright install chromium`, or set `CHROMIUM_PATH` (§4.5).

**Ollama connection refused** — `ollama serve` is not running, or
`OLLAMA_URL` points somewhere else. Default is `http://localhost:11434`.

---

## Channel Operating Kit

Beyond the code, [`docs/channel-operating-kit/`](docs/channel-operating-kit/)
holds the non-automated half of running a faceless AI-tools channel: the weekly
production checklist, time-blocked schedule, Notion database schemas,
thumbnail/title testing method, and a 25-point weekly scoring framework. Start at
[the kit README](docs/channel-operating-kit/README.md).

## Documentation

Anime pipeline design docs, in reading order:

- [Orchestration](docs/anime-pipeline/01-orchestration.md) — graph, state machine, gates, events
- [QC framework](docs/anime-pipeline/02-qc-framework.md) — weights, thresholds, the publish gate
- [Anime edit checklist](docs/anime-pipeline/03-anime-edit-checklist.md) — frame-accurate timings
- [Tracker schemas](docs/anime-pipeline/04-tracker-schemas.md) — Notion / Airtable
- [Canon memory](docs/anime-pipeline/05-canon-memory.md) — drift prevention, consistency guard, writeback
- [Continuity enforcement](docs/anime-pipeline/06-continuity-enforcement.md) — registry, timeline, contradictions, the three gates
- [Continuity hardening](docs/anime-pipeline/07-continuity-hardening.md) — normalisation, aliases, retcon approvals, causality, the adversarial suite
- [Access control and deferred work](docs/anime-pipeline/08-access-and-jobs.md) — passwords, tokens, workspaces, the job queue, correlation ids
- [Generation integration](docs/anime-pipeline/09-generation-integration.md) — providers, prompt templates, canon-bound prompts, provenance
- [Admin console](docs/anime-pipeline/10-admin-console.md) — the Next.js front end

Component READMEs: [`anime_pipeline/`](anime_pipeline/README.md) ·
[`frontend/`](frontend/README.md) · [`desktop_app/`](desktop_app/README.md)

## Repository layout

```
youtube-pipeline/
├── pipeline.py              # §2 orchestrator
├── llm_providers.py         # Ollama / Groq / Gemini abstraction
├── content_generator.py     # script, title, description
├── media_generator.py       # Edge TTS audio + images
├── video_assembler.py       # MoviePy assembly
├── youtube_uploader.py      # YouTube Data API upload
├── web_ui.py                # §6.1 Flask UI
├── chatterbox_app.py        # §5 TTS studio
├── chatterbox_studio/       #     its engine, queue, models registry
├── requirements.txt         # §2 dependencies
├── requirements-chatterbox.txt
├── config.ini               # non-secret defaults
├── .env.example             # secrets template
│
├── anime_pipeline/          # §3 FastAPI backend
│   ├── app/                 #   core, models, services, agents, api
│   ├── migrations/          #   alembic, through 0008
│   ├── scripts/             #   muapi_live_check.py
│   ├── tests/               #   361 tests
│   └── pyproject.toml
│
├── frontend/                # §4 Next.js admin console
│   ├── app/ components/ hooks/ lib/
│   ├── smoke.mjs            #   Playwright end-to-end check
│   └── package.json
│
├── desktop_app/  desktop-ui/  tauri-app/   # §6 wrappers
├── templates/               # web UI HTML
└── docs/                    # design docs + channel operating kit
```
