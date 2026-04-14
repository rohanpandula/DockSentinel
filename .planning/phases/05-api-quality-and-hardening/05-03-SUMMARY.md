---
phase: 05-api-quality-and-hardening
plan: "03"
subsystem: infra
tags: [docker, healthcheck, non-root, named-volume, security, docker-compose]

dependency_graph:
  requires:
    - phase: 05-02
      provides: pytest-cov gate and test infrastructure already in place
  provides:
    - Dockerfile with non-root UID 1000 appuser, HEALTHCHECK targeting /api/health, cached deps layer
    - docker-compose.yml with named volume docksentinel_data, healthcheck block, Codex/Gemini paths under /home/appuser
  affects: [ops runbook, README deployment instructions, CI Docker build]

tech_stack:
  added: []
  patterns:
    - Non-root container pattern — groupadd/useradd with fixed UID 1000 before COPY, USER directive before CMD
    - Docker layer cache boundary — requirements.txt + pip install before COPY . /app
    - Compose healthcheck mirrors Dockerfile HEALTHCHECK (drift-prevention)
    - Named volume for persistent SQLite — eliminates bind-mount permission flap

key_files:
  created: []
  modified:
    - Dockerfile
    - docker-compose.yml

key_decisions:
  - "start-period=15s chosen to allow Alembic migrations on cold boot without flapping — live verify confirmed healthy within 30s including migration run"
  - "Named volume docksentinel_data replaces ./data bind mount — named volumes are container-owned and created with the invoking UID, eliminating PermissionError on first write"
  - "CODEX_HOME and GEMINI_HOME relocated from /root/... to /home/appuser/... — mandatory because USER appuser runs after npm global install; config paths must match the process user's home"
  - "SECRET_KEY uses :? required-var syntax preserved — operator must set the variable; no default to avoid silent security weakening"

requirements-completed: [DOCK-01, DOCK-02, DOCK-03, DOCK-04]

duration: ~35min
completed: "2026-04-14"
---

# Phase 05 Plan 03: Docker Hardening Summary

**Dockerfile runs as UID 1000 appuser with HEALTHCHECK on /api/health, named volume for SQLite persistence, and Codex/Gemini CLI paths relocated to /home/appuser — live-verified healthy within 30s with zero permission errors.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-04-14
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint — approved)
- **Files modified:** 2

## Accomplishments

- Dockerfile now creates `appuser` (UID/GID 1000) before any COPY, owns `/data` and `/app`, and drops privileges via `USER appuser` before `CMD`
- `HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3` targets the existing `/api/health` endpoint — no new endpoint added
- Dependency install cache layer preserved: `COPY requirements.txt` + `RUN pip install` sits before `COPY . /app` (DOCK-03)
- docker-compose.yml switches from `./data:/data` bind mount to `docksentinel_data` named volume, adds `healthcheck:` block matching the Dockerfile directive, relocates `CODEX_HOME`/`GEMINI_HOME` to `/home/appuser/...`
- Live verification on the developer's machine confirmed all DOCK-01..04 requirements

## Task Commits

1. **Task 1: Harden Dockerfile — non-root user, HEALTHCHECK, cached deps** - `0e0a0c7` (feat)
2. **Task 2: Update docker-compose.yml — named volume, healthcheck, CLI paths** - `2072244` (feat)
3. **Task 3: Human-verify checkpoint** — APPROVED (no code commit — runtime verification)

## Files Created/Modified

- `Dockerfile` — non-root `appuser` UID 1000, `HEALTHCHECK` on `/api/health`, `--chown=appuser:appuser` on all COPY layers, `chown -R appuser:appuser /data /app`, `USER appuser` before `CMD`
- `docker-compose.yml` — named volume `docksentinel_data:/data`, `healthcheck:` block, `CODEX_HOME=/home/appuser/.codex`, `GEMINI_HOME=/home/appuser/.gemini`, host bind mounts updated to `${HOME}/.*:/home/appuser/.*:rw`, `restart: unless-stopped`

## Live Verification Evidence (Task 3 — Human Approved)

| Check | Command | Result |
|-------|---------|--------|
| DOCK-01: Non-root user | `docker exec docksentinel id` | `uid=1000(appuser) gid=1000(appuser) groups=1000(appuser)` |
| DOCK-02: Healthcheck passes | `docker inspect docksentinel --format '{{.State.Health.Status}}'` | `healthy` |
| DOCK-02: Endpoint reachable | `docker exec docksentinel curl -fsS http://localhost:5000/api/health` | `{"status":"ok", ...}` (200 OK) |
| DOCK-04: Named volume owner | `docker exec docksentinel ls -la /data/` | `docksentinel.db` owned by `appuser:appuser` |
| Cleanup | `docker compose down` | Completed successfully |

All five DOCK requirements verified in a single `docker compose up` run.

## Operator Migration Note (Existing ./data Bind Mount)

If the host has an existing `./data/docksentinel.db` from before this plan, migrate it to the named volume with:

```bash
docker compose up -d --no-start
docker run --rm \
  -v "$(pwd)/data":/src \
  -v docksentinel_docksentinel_data:/dst \
  alpine sh -c "cp -a /src/. /dst/"
docker compose up -d
```

This is informational — README update is out of scope for DOCK-* requirements and should be added in a follow-up.

## Decisions Made

- `start-period=15s` — gives Alembic migration time on cold boot before healthcheck counts failures. The live verify confirmed this was sufficient; if migrations grow, bump to `30s`.
- Named volume over bind mount — `docksentinel_data` is created with the invoking container's UID on first init, so no manual `chown` is required on the host (Pitfall P-04 avoided).
- `CODEX_HOME` and `GEMINI_HOME` relocated to `/home/appuser` — the `npm install -g` step runs as root (before `USER appuser`), so the CLI binaries land in `/usr/lib/node_modules` and are world-executable. Only their config paths need to match the running user's home directory.
- `SECRET_KEY=${SECRET_KEY:?...}` required-var pattern preserved — operators must export `SECRET_KEY` in shell or `.env`; no default supplied.

## Deviations from Plan

None — plan executed exactly as written. Both auto tasks passed on first attempt; the human-verify checkpoint was approved without requiring any fix iteration.

## Observations (Non-Blocking)

**docker-watcher `host.docker.internal:23751` connection refused in logs**

During live verification a log entry showed the docker watcher failing to connect to `host.docker.internal:23751`. This is the docker-socket-proxy address. In the developer's test environment the socket proxy was not running, so the watcher marks `runtime_status` as degraded. This is expected and pre-existing behavior — `/api/health` still returns HTTP 200 because the health endpoint reports `status: ok` while flagging the runtime degradation separately. Not introduced by this plan; flagged here for ops awareness.

## Threat Surface Scan

No new network endpoints, auth paths, or schema changes introduced. The trust boundary changes documented in the plan's threat model were addressed:

| Threat | Disposition | Outcome |
|--------|-------------|---------|
| T-05-03-01: Root container escape | Mitigated | `USER appuser` (UID 1000) applied |
| T-05-03-02: Named volume tampering | Mitigated | Volume owned by appuser; no `--privileged` |
| T-05-03-03: SECRET_KEY in compose | Mitigated | `:?` required-var preserved |
| T-05-03-06: Healthcheck flap on cold boot | Mitigated | `start_period=15s` + `retries=3` |
| T-05-03-05: Host bind mount (codex/gemini) | Mitigated by design | Required for CLI backends; documented |

## Known Stubs

None.

## Next Phase Readiness

Phase 5 (API Quality and Hardening) is now complete — all three plans (05-01, 05-02, 05-03) executed and verified:

- 05-01: Pydantic schemas, Flask-Pydantic validation, pagination on /api/insights and /api/reports
- 05-02: pytest-cov gate at 80% (actual: 90.84%), shared conftest fixtures, pipeline/pagination/schema tests
- 05-03: Docker non-root, HEALTHCHECK, named volume, Codex/Gemini CLI path relocation

All 46 tests pass. Docker container is production-hardened. Coverage gate is enforced in CI.

---

## Self-Check

### Files exist
- `Dockerfile`: FOUND (modified)
- `docker-compose.yml`: FOUND (modified)

### Commits exist
- `0e0a0c7`: Task 1 — Dockerfile hardening
- `2072244`: Task 2 — docker-compose.yml updates

## Self-Check: PASSED

---
*Phase: 05-api-quality-and-hardening*
*Completed: 2026-04-14*
