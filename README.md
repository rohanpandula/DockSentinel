# DockSentinel

DockSentinel is a self-hosted AIOps observability agent for Docker environments. It monitors container logs in near real-time, filters noise, uses either OpenAI-compatible APIs or CLI-based LLM backends for semantic triage, sends Telegram alerts for critical failures, and generates nightly health briefings.

![Overview dashboard](docs/screenshots/overview.png)

## Features

- **Minimalist ops dashboard** — custom design system, Geist typography, single-accent palette, tabular numerics, proper empty/loading/error states
- Dual LLM transports:
  - API mode (any OpenAI-compatible endpoint — Ollama, vLLM, OpenAI, etc.)
  - CLI mode (pluggable backends: `codex`, `claude`, `gemini`, `ollama`)
- Real-time Sentinel watchdog with Docker event-driven auto attach/detach
- Sliding-window log buffering with char/token budget limits
- Heuristic prefilter with word-boundary matching and JSON false-positive suppression
- LLM call reduction: chunk dedup, per-container rate limiting, keyword batching
- **Per-container sliding-window coalescing** — hold matched chunks for N seconds per container, reset on each new arrival, then ship the whole batch to the LLM in a single call
- Single-concurrency lock for CLI backend calls (one call at a time globally)
- Prompt Engineering Studio (editable, versioned prompt templates)
- Telegram critical alerts with cooldown and global rate limiting
- Nightly briefing generation and report archive
- **mDNS publishing** — opt-in `<hostname>.local` resolution via zeroconf (no avahi/dbus needed)
- **Container dropdown** on the Overview — pick from running containers or type a name manually
- Hardened container: non-root (uid 1000), `HEALTHCHECK`, named volume

## Screenshots

| | |
| --- | --- |
| **Overview** — sentinel status, today's counts, recent events, analyze-now form | **Events** — searchable archive with root-cause & fix suggestions |
| ![](docs/screenshots/overview.png) | ![](docs/screenshots/events.png) |
| **Settings** — grouped into LLM, input budgets, alerts/rate-limits, scheduler | **Prompts** — edit versioned prompt templates |
| ![](docs/screenshots/settings.png) | ![](docs/screenshots/prompts.png) |
| **Reports** — nightly briefings archive | **Exclusions** — container patterns to skip |
| ![](docs/screenshots/reports.png) | ![](docs/screenshots/exclusions.png) |

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
- `DOCKER_HOST` – Docker daemon endpoint; default is the local socket (`unix:///var/run/docker.sock`). Set to a `tcp://` address to use a remote daemon
- `APP_PORT` – port Flask binds to inside the container (default `5000`). Set to `80` for macvlan deployments where the container gets its own LAN IP
- `MDNS_ENABLED` – set to `true` to publish `<hostname>.local` via multicast DNS
- `MDNS_HOSTNAME` – the name to advertise (default `docksentinel`)
- `MDNS_PORT` – port advertised in the `_http._tcp.local.` service record
- `SECRET_KEY` **required** in non-development environments; must be ≥ 16 characters and not a placeholder value (e.g. `change-me`, `dev-secret-key`)

## Coalescing Noisy Containers

Set `chunk_coalesce_window_seconds` in Settings (default `0` = disabled) to hold matched log chunks per container in a sliding window. Each new matching chunk for the same container resets the timer; when the window elapses without new arrivals, the entire batch ships to the LLM in a single call and produces **one** summarized alert instead of dozens. A good starting value is `300` (five minutes).

## Unraid / macvlan Deployment

See `docker-compose.unraid.example.yml` for a reference config. Highlights:

- Gives the container its own LAN IP on `br0` (no host port mapping)
- Binds Flask to port 80 via `sysctls: net.ipv4.ip_unprivileged_port_start=80` — no root required
- Publishes `docksentinel.local` via mDNS
- Mounts the docker socket read-only and grants `group_add: [281]` so the non-root process can read it (verify the docker GID on your host)

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

## LLM Call Reduction

DockSentinel includes several layers to minimize unnecessary LLM calls:

- **Prefilter word-boundary matching** — keywords like `error` only match whole words, not JSON keys like `"error":0` or compound identifiers like `error_count`
- **Chunk dedup** — if the same log content (by SHA-256 hash) was already analyzed within the configurable dedup window, the duplicate is skipped (`dedup_window_seconds`, default 300)
- **Per-container rate limiting** — each container is capped at N LLM calls per rolling window (`container_rate_limit_count` / `container_rate_limit_window_seconds`, default 10 per hour)
- **Keyword flush delay** — after a keyword hit, the log buffer collects additional context lines before flushing to the LLM (`keyword_flush_delay_lines`, default 5)

All settings are configurable from the Settings page or via `PUT /api/settings`.

## Testing

```bash
python -m pytest -q
```

The test suite contains 31 tests covering API endpoints, sentinel pipeline (including excluded-event recording, cooldown dedup, chunk dedup, per-container rate limiting), prefilter word-boundary and JSON-benign filtering, log buffer keyword batching, briefing fallback, runtime lock health checks, and UI route smoke tests.

## Notes

- This MVP is optimized for trusted home-lab/self-hosted usage (no auth layer yet).
- Roadmap items such as RAG memory, Slack/Discord alerts, and anomaly graphs are intentionally out of scope for this phase.
