---
phase: 03-alembic-migration-infrastructure
plan: 01
subsystem: database
tags: [alembic, sqlalchemy, sqlite, migrations, schema]

# Dependency graph
requires:
  - phase: 02-repository-layer
    provides: "ORM models and db.metadata registered via app.extensions.db"
provides:
  - "alembic.ini at project root with SQLite-safe batch mode configuration"
  - "migrations/env.py reading db.metadata via app.extensions.db (no create_app dependency)"
  - "0001_initial_schema.py baseline revision capturing all 7 ORM tables"
  - "0002_settings_compat_cols.py revision encoding 8 settings columns with server_default"
affects: [blueprints, future-phases, docker-setup]

# Tech tracking
tech-stack:
  added: [alembic==1.18.4]
  patterns:
    - "SQLite batch mode via render_as_batch=True in both offline and online migration paths"
    - "env.py reads DATABASE_URL from environment, never hardcodes sqlalchemy.url in alembic.ini"
    - "env.py imports db from app.extensions + app.models for side-effects, no create_app"
    - "Manual revision files for schema compat columns (not autogenerate) to control server_default"

key-files:
  created:
    - alembic.ini
    - migrations/env.py
    - migrations/script.py.mako
    - migrations/versions/0001_initial_schema.py
    - migrations/versions/0002_settings_compat_cols.py
  modified:
    - requirements.txt

key-decisions:
  - "Revision 1 excludes the 8 compat columns from settings table — revision 2 adds them via batch_alter_table, correctly modelling v0.1->v0.2 schema evolution"
  - "Revision 2 uses server_default (not Python-side default) so existing rows get values on ALTER TABLE without IntegrityError"
  - "alembic.ini has no sqlalchemy.url value — env.py reads DATABASE_URL env var at runtime, falling back to ./data/docksentinel.db"
  - "env.py does NOT import create_app — imports only db and app.models to avoid Flask app context dependency at migration time"

patterns-established:
  - "SQLite batch mode: render_as_batch=True in both run_migrations_offline and run_migrations_online"
  - "Column additions to existing tables always use server_default, never Python default"

requirements-completed: [MIG-01, MIG-02, MIG-03]

# Metrics
duration: 3min
completed: 2026-04-04
---

# Phase 3 Plan 01: Alembic Migration Infrastructure Summary

**Alembic initialized with SQLite batch mode, two revisions encoding the baseline schema (7 tables) and the 8 settings compat columns with proper server_default**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-05T02:28:05Z
- **Completed:** 2026-04-05T02:30:50Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Alembic fully initialized: alembic.ini, env.py, script template, versions directory
- env.py imports db.metadata from app.extensions without requiring Flask app context — no create_app dependency
- Revision 1 captures all 7 ORM tables as baseline (analysis_events, daily_reports, exclusion_rules, prompt_templates, schema_version, sentinel_state, settings) without compat columns
- Revision 2 adds 8 settings compat columns via batch_alter_table with server_default for safe ALTER on existing rows
- Both upgrade and downgrade paths verified on fresh SQLite database
- All 31 existing tests continue to pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Initialize Alembic configuration and env.py** - `6a6e2dc` (chore)
2. **Task 2: Create initial schema migration and settings compat migration** - `6ae31be` (feat)

## Files Created/Modified
- `alembic.ini` - Alembic CLI config with script_location=migrations, no hardcoded DB URL
- `migrations/env.py` - Alembic environment connecting to Flask-SQLAlchemy metadata with render_as_batch=True
- `migrations/script.py.mako` - Standard Alembic revision template
- `migrations/versions/.gitkeep` - Keeps versions directory in git
- `migrations/versions/0001_initial_schema.py` - Baseline revision: 7 tables, no compat columns
- `migrations/versions/0002_settings_compat_cols.py` - Adds 8 settings columns via batch_alter_table with server_default
- `requirements.txt` - Added alembic==1.18.4

## Decisions Made
- Revision 1 does not include the 8 compat columns in the settings table; revision 2 adds them. This correctly models the v0.1 to v0.2 schema evolution and allows downgrade -1 to cleanly remove them.
- server_default used instead of Python default for all compat column additions — required so SQLite emits DEFAULT SQL on the ALTER TABLE, preventing IntegrityError on tables with existing rows.
- No sqlalchemy.url in alembic.ini — env.py reads DATABASE_URL env var at runtime, making the config portable across environments.
- env.py does not import create_app or the Flask app object, only db from app.extensions and app.models for side-effect registration. This avoids Flask application context dependency during alembic CLI runs.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - autogenerate ran cleanly, both migration revisions applied and reversed without errors.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Alembic is ready for use: `alembic upgrade head` applies all migrations on fresh databases
- Existing databases can be stamped: `DATABASE_URL=<url> alembic stamp head` (prep for plan 02)
- All 31 tests pass — no regressions introduced
- Plan 02 (stamp existing databases + remove _ensure_settings_schema_compat) can proceed immediately

## Self-Check: PASSED

- alembic.ini: FOUND
- migrations/env.py: FOUND
- migrations/versions/0001_initial_schema.py: FOUND
- migrations/versions/0002_settings_compat_cols.py: FOUND
- 03-01-SUMMARY.md: FOUND
- Commit 6a6e2dc: FOUND
- Commit 6ae31be: FOUND

---
*Phase: 03-alembic-migration-infrastructure*
*Completed: 2026-04-04*
