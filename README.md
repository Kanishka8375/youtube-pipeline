# YouTube Content Creation Pipeline

Automated video generation, editing, and uploading pipeline using **free models only**.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up **free LLM provider** (choose one):

   **Option A: Ollama (Local - Recommended)**
   ```bash
   # Install ollama from https://ollama.com
   ollama pull llama3.2
   ollama serve
   ```
   
   **Option B: Groq (Cloud - 8000 req/day free)**
   - Get free API key at [groq.com](https://groq.com)
   - Set `GROQ_API_KEY` in `.env`
   
   **Option C: Gemini (Cloud - 60 req/min free)**
   - Get free API key at [Google AI Studio](https://aistudio.google.com)
   - Set `GEMINI_API_KEY` in `.env`

3. Set up YouTube API credentials:
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a project and enable YouTube Data API v3
   - Create OAuth 2.0 credentials
   - Download `client_secrets.json` to project root

4. Configure environment:
```bash
cp .env.example .env
# Edit .env with your preferred LLM settings
```

## Usage

```bash
# Auto-detect available provider
python pipeline.py --topic "Your Video Topic" --duration 60

# Use specific provider
CONTENT_PROVIDER=ollama python pipeline.py --topic "Your Video Topic"
```

## Free Model Options

| Provider | Model | Limits | Best For |
|----------|-------|--------|----------|
| Ollama | llama3.2, mistral | Unlimited | Privacy, no API keys |
| Groq | llama-3.3-70b | 8000 req/day | Speed, quality |
| Gemini | gemini-1.5-flash | 60 req/min | Reliability |

TTS uses Edge TTS (Microsoft Edge, free). Video assembly uses MoviePy (free).

## Channel Operating Kit

Beyond the code, [`docs/channel-operating-kit/`](docs/channel-operating-kit/) holds the
non-automated half of running a faceless AI-tools channel: the weekly production
checklist, time-blocked schedule, Notion database schemas, thumbnail/title testing
method, and a 25-point weekly scoring framework. Start at
[the kit README](docs/channel-operating-kit/README.md).

## Anime Pipeline (multi-agent backend)

[`anime_pipeline/`](anime_pipeline/) is a separate FastAPI + SQLAlchemy service for
running a serialized anime channel with 13 specialist agents: a gated episode
workflow, schema-enforced agent handoffs, and a computed QC model that decides
whether an episode ships. See [its README](anime_pipeline/README.md) and the
[design docs](docs/anime-pipeline/).

## Pipeline Structure

- `llm_providers.py` - Multi-provider LLM abstraction (Ollama, Groq, Gemini)
- `content_generator.py` - Script, title, description generation
- `media_generator.py` - TTS audio (Edge TTS, free) and image generation
- `video_assembler.py` - Video editing and assembly
- `youtube_uploader.py` - YouTube upload functionality
- `pipeline.py` - Main orchestrator

## Directory Structure

```
windsurf-project/
├── llm_providers.py     # Free LLM provider implementations
├── content_generator.py
├── media_generator.py
├── video_assembler.py
├── youtube_uploader.py
├── pipeline.py
├── requirements.txt
├── .env.example
├── client_secrets.json  # YouTube API credentials
├── output/              # Generated videos
├── assets/              # Stock images/audio
└── temp/                # Temporary files
```

## Testing Providers

```python
from llm_providers import LLMProviderFactory

# List available providers
print(LLMProviderFactory.list_available())

# Test specific provider
provider = LLMProviderFactory.create("groq")
response = provider.generate("Write a haiku about AI")
print(response.content)
```
