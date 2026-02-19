# DockSentinel

DockSentinel is a self-hosted AIOps observability agent for Docker environments. It monitors container logs in near real-time, filters noise, uses either OpenAI-compatible APIs or CLI-based LLM backends for semantic triage, sends Telegram alerts for critical failures, and generates nightly health briefings.

## Features

- Dual LLM transports:
  - API mode (OpenAI-compatible `base_url` + `api_key` + `model`)
  - CLI mode (pluggable backends: `codex`, `claude`, `gemini`, `ollama`)
- Real-time Sentinel watchdog with Docker event-driven auto attach/detach
- Sliding-window log buffering with char/token budget limits
- Heuristic prefilter for high-signal keywords
- Single-concurrency lock for CLI backend calls (one call at a time globally)
- Prompt Engineering Studio (editable, versioned prompt templates)
- Telegram critical alerts with cooldown and global rate limiting
- Nightly briefing generation and report archive
- Flask + Tailwind dashboard for full configuration and operations

## Architecture

- Flask + Jinja2 web app
- SQLite persistence (`/data/docksentinel.db` by default)
- RuntimeCoordinator with file lock (`/data/runtime.lock`) to prevent duplicate watchdog/scheduler threads
- Docker SDK for events and live logs (local socket or remote `DOCKER_HOST`)
- APScheduler for nightly report jobs

## Project Layout

```text
app/
  api/          # Flask API blueprints
  models/       # SQLAlchemy models
  services/     # Coordinator, sentinel, LLM client, CLI backends, etc.
  templates/    # Jinja2 HTML pages
  static/       # Frontend JS
llm-backends/   # Pluggable CLI backend scripts (stdin->stdout contract)
tests/
Dockerfile
docker-compose.yml
requirements.txt
```

## Requirements

- Python 3.12+
- Docker and Docker Compose
- For CLI mode: relevant CLI installed/authenticated (`codex`, `claude`, `gemini`, or `ollama`)

## Quick Start (Docker Compose)

```bash
git clone https://github.com/rohanpandula/DockSentinel.git
cd DockSentinel
docker compose up -d --build
```

Open the UI at [http://localhost:5000](http://localhost:5000).

Default compose mapping in this repo is [http://localhost:5050](http://localhost:5050).

## CLI Backend Mode (No API usage)

1. In Settings, set:
   - `LLM Transport` = `cli`
   - `CLI Backend` = `codex` (or another installed backend)
2. Tune:
   - `CLI Timeout Seconds`
   - `CLI Max Retries`
3. Click `Test LLM` to verify backend execution.

Backend wrappers live in `llm-backends/` and follow a simple stdin/stdout contract:

- Script reads one prompt from **stdin**
- Script writes the model response to **stdout**
- Non-zero exit code signals failure

To add a new backend, create `llm-backends/<name>.sh`, make it executable, and it will appear as an option.

## Local Development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

## Environment Variables

Copy `.env.example` and adjust values as needed.

- `DATABASE_URL` default (development): `sqlite:///./data/docksentinel.db`
- `RUNTIME_LOCK_PATH` default (development): `./data/runtime.lock`
- `START_COORDINATOR` default: `true`
- `CLI_BACKENDS_DIR` default: `/app/llm-backends` in Docker
- `DOCKER_HOST` – set to a `tcp://` address to use a remote Docker daemon (the default compose uses `tcp://host.docker.internal:23751` for a local Socat/TCP tunnel instead of the Docker socket)
- `CODEX_HOME` – path to Codex credentials directory (mounted read-only in the default compose)
- `SECRET_KEY` **required** in non-development environments; must be ≥ 16 characters and not a placeholder value (e.g. `change-me`, `dev-secret-key`)

## API Endpoints

- `GET /api/health`
- `GET /api/settings`
- `PUT /api/settings`
- `POST /api/settings/test-llm`
- `GET /api/exclusions`
- `POST /api/exclusions`
- `DELETE /api/exclusions/{id}`
- `GET /api/prompts`
- `PUT /api/prompts/{key}`
- `POST /api/prompts/{key}/reset`
- `GET /api/sentinel/status`
- `POST /api/sentinel/toggle`
- `POST /api/sentinel/analyze-now`
- `GET /api/insights`
- `GET /api/reports`
- `GET /api/reports/{id}`
- `POST /api/reports/generate`
- `POST /api/telegram/test`

## Prompt Templates

Seeded on first startup:

- `SENTINEL_SYSTEM`
- `SENTINEL_ANALYSIS`
- `JSON_OUTPUT_GUARD`
- `NIGHTLY_SYSTEM`
- `NIGHTLY_REPORT`

Prompts are editable from the Prompt Studio page and versioned in SQLite.

## Default Exclusions

Seeded on first startup:

- `docksentinel`
- `ollama`
- `portainer`
- `open-webui`

## Docker Host / Remote Docker

The default `docker-compose.yml` connects to the Docker daemon via a TCP tunnel (`DOCKER_HOST=tcp://host.docker.internal:23751`) rather than mounting `/var/run/docker.sock`. This avoids socket permission issues and works well with Socat-based Docker TCP proxies. To use a direct socket mount instead, remove the `DOCKER_HOST` env var and add a volume for `/var/run/docker.sock`.

## Testing

```bash
python -m pytest -q
```

The test suite currently contains 21 tests covering API endpoints, sentinel pipeline (including excluded-event recording, cooldown dedup, and rate limiting), briefing fallback, log buffer, runtime lock health checks, and UI route smoke tests.

## Notes

- This MVP is optimized for trusted home-lab/self-hosted usage (no auth layer yet).
- Roadmap items such as RAG memory, Slack/Discord alerts, and anomaly graphs are intentionally out of scope for this phase.
