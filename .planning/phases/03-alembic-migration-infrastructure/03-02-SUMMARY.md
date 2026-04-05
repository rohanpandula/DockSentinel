---
phase: 03-alembic-migration-infrastructure
plan: "02"
subsystem: app-factory, docker
tags: [alembic, migrations, docker, db-create-all, schema-compat]
dependency_graph:
  requires: [03-01]
  provides: [MIG-02, MIG-03, MIG-04]
  affects: [app/__init__.py, docker-entrypoint.sh, Dockerfile]
tech_stack:
  added: []
  patterns:
    - "db.create_all() gated to TESTING=True only"
    - "Docker entrypoint with idempotent alembic stamp for v0.2 databases"
    - "alembic upgrade head runs before Flask starts in production"
key_files:
  created:
    - docker-entrypoint.sh
  modified:
    - app/__init__.py
    - Dockerfile
decisions:
  - "_ensure_settings_schema_compat deleted — Alembic migrations own all schema changes from 03-01 onwards"
  - "docker-entrypoint.sh uses Python subprocess (not inline shell) to detect v0.2 databases before stamping"
  - "TESTING gate uses app.config.get('TESTING') so test suite (which sets TESTING=True) continues using db.create_all() unmodified"
  - "docker-compose.yml unchanged — bind mount ./data:/data already persists SQLite database across restarts"
metrics:
  duration_minutes: 2
  completed_date: "2026-04-05"
  tasks_completed: 2
  files_changed: 3
---

# Phase 03 Plan 02: Docker Entrypoint and Schema Init Cleanup Summary

Gate `db.create_all()` to test-only, delete hardcoded ALTER TABLE compat function, and wire Docker containers to run `alembic upgrade head` on startup with idempotent stamping for pre-existing v0.2 databases.

## What Was Built

### Task 1: Gate db.create_all() and delete _ensure_settings_schema_compat

**app/__init__.py — two changes:**

1. Deleted `_ensure_settings_schema_compat()` function (22 lines of hardcoded `ALTER TABLE` SQL that duplicated what Alembic revision 2 now handles). Also removed the unused `from sqlalchemy import inspect, text` import.

2. Gated `db.create_all()` behind `if app.config.get("TESTING")`:
   ```python
   with app.app_context():
       if app.config.get("TESTING"):
           db.create_all()
       _seed_defaults()
   ```
   Test suite continues to call `db.create_all()` (tests set `TESTING=True` via `AppConfig.from_env()`). Production uses `alembic upgrade head` via the new entrypoint instead.

**Commit:** `2345d35`

### Task 2: Create Docker Entrypoint and Update Dockerfile

**docker-entrypoint.sh (new):** Shell script that:
1. Detects if the database is a v0.2 installation (has `settings` table but no `alembic_version` table)
2. If detected, runs `alembic stamp head` to mark it as already at current schema
3. Always runs `alembic upgrade head` (idempotent — no-op if already current)
4. Launches Flask with `exec` to replace the shell process

The Python detection block runs first and prints "yes" or "no", then shell conditionally calls `alembic stamp head`. This pattern keeps all shell-level commands as literal strings so grep-based verification works.

**Dockerfile:** Added two lines after `COPY . /app`:
```dockerfile
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
```
Changed CMD from direct flask invocation to `/app/docker-entrypoint.sh`.

**docker-compose.yml:** Unchanged — bind mount `./data:/data` already provides SQLite persistence.

**Commit:** `e027a93`

## Verification Results

| Check | Result |
|-------|--------|
| `_ensure_settings_schema_compat` deleted | 0 occurrences in app/__init__.py |
| `db.create_all()` gated to TESTING | 1 match for `if app.config.get("TESTING")` |
| `docker-entrypoint.sh` exists and executable | Pass |
| `docker-entrypoint.sh` contains `alembic stamp head` | Pass |
| `docker-entrypoint.sh` contains `alembic upgrade head` | Pass |
| Dockerfile CMD updated | `/app/docker-entrypoint.sh` |
| All 31 tests pass | 31 passed, 0 failed |

Note: Verification 6 (`DATABASE_URL=sqlite:///./data/verify_final.db alembic upgrade head`) requires `alembic.ini` and `migrations/` from 03-01. This worktree is a parallel executor — the alembic infrastructure will be present after all worktrees merge into main.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restructured docker-entrypoint.sh stamping logic for grep compatibility**
- **Found during:** Task 2 verification
- **Issue:** Plan's verify command uses `grep -q "alembic stamp head"` but initial implementation had `subprocess.run(["alembic", "stamp", "head"])` inside a Python heredoc — the literal string `alembic stamp head` was not present
- **Fix:** Restructured to use Python heredoc only for detection (prints "yes"/"no"), then called `alembic stamp head` as a shell command in a conditional block. Same behavior, grep-verifiable.
- **Files modified:** docker-entrypoint.sh
- **Commit:** e027a93 (same task commit — fixed before committing)

## Known Stubs

None — all changes are structural (gating/deletion) and Docker infrastructure. No data flows or UI stubs introduced.

## Self-Check: PASSED

- app/__init__.py: FOUND
- docker-entrypoint.sh: FOUND
- Dockerfile: FOUND
- commit 2345d35 (Task 1): FOUND
- commit e027a93 (Task 2): FOUND
