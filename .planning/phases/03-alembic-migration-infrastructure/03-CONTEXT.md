# Phase 3: Alembic Migration Infrastructure - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning
**Source:** Auto-mode (recommended defaults selected)

<domain>
## Phase Boundary

Replace the brittle `_ensure_settings_schema_compat` function (8 hardcoded ALTER TABLE statements) with Alembic-managed schema evolution. Initialize Alembic with SQLite batch mode, generate a baseline migration from current models, convert the compat function into a proper revision, gate `db.create_all()` to test-only, and update Docker entrypoint to run `alembic upgrade head`. All 31 existing tests pass with no modifications to test logic.

</domain>

<decisions>
## Implementation Decisions

### Alembic Configuration
- **D-01:** Initialize Alembic with `render_as_batch=True` in `env.py` for SQLite compatibility (SQLite doesn't support most ALTER TABLE operations natively — batch mode recreates the table). Per MIG-01.
- **D-02:** `env.py` imports Flask-SQLAlchemy's `db.metadata` as the `target_metadata` so autogenerate can diff against the ORM models.
- **D-03:** `alembic.ini` sets `sqlalchemy.url` to empty — `env.py` reads `SQLALCHEMY_DATABASE_URI` from Flask app config or `DATABASE_URL` env var at runtime.

### Initial Migration Strategy
- **D-04:** Autogenerate the initial migration from current ORM models using `alembic revision --autogenerate -m "initial schema"`. This captures the complete current schema (all 7 tables) as the baseline.
- **D-05:** Existing v0.2 databases are stamped with `alembic stamp head` so Alembic treats them as current and doesn't try to re-create tables. Per MIG-02.
- **D-06:** The stamp operation is documented in README and handled in Docker entrypoint logic (if `alembic_version` table doesn't exist, stamp before upgrade).

### Schema Compat Replacement
- **D-07:** The 8 ALTER TABLE statements in `_ensure_settings_schema_compat` are converted to a single Alembic revision (revision 2) using `batch_alter_table('settings')` with `add_column()` for each of: `llm_transport`, `cli_backend`, `cli_timeout_seconds`, `cli_max_retries`, `dedup_window_seconds`, `container_rate_limit_count`, `container_rate_limit_window_seconds`, `keyword_flush_delay_lines`. Per MIG-03.
- **D-08:** The downgrade for revision 2 uses `batch_alter_table('settings')` with `drop_column()` for each of the 8 columns.
- **D-09:** After the Alembic revision is verified working, `_ensure_settings_schema_compat` is deleted from `app/__init__.py` and its call removed from `create_app()`.

### Test Environment Strategy
- **D-10:** `db.create_all()` call in `create_app()` is gated behind `if app.config.get("TESTING")`. Tests continue to use `db.create_all()` via the test app factory — no change to test fixtures or logic. Per MIG-04.
- **D-11:** Production startup uses `alembic upgrade head` in the Docker CMD/entrypoint. The Dockerfile CMD is updated to run migrations before starting Flask.
- **D-12:** The `_seed_defaults()` function stays in `create_app()` (called after either `db.create_all()` in test or `alembic upgrade head` in production) — it seeds default data, not schema.

### Claude's Discretion
- Exact alembic directory structure (`alembic/` vs `migrations/`)
- Whether to use a shell script entrypoint or inline the migration command in Docker CMD
- Exact revision message wording
- Whether `_seed_defaults()` needs any adjustment for the new flow

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §Migration Infrastructure — MIG-01, MIG-02, MIG-03, MIG-04 define the four acceptance criteria
- `.planning/ROADMAP.md` §Phase 3 — Goal, success criteria, dependency on Phase 2

### Code to modify
- `app/__init__.py` lines 82-103 — `_ensure_settings_schema_compat()` function with 8 ALTER TABLE statements (to be deleted)
- `app/__init__.py` lines 319-322 — `db.create_all()` and `_ensure_settings_schema_compat()` calls in `create_app()` (to be gated/removed)
- `app/extensions.py` — `db` instance used by Flask-SQLAlchemy (Alembic env.py needs to import this)

### Models (schema source of truth for autogenerate)
- `app/models/events.py` — AnalysisEvent
- `app/models/exclusions.py` — ExclusionRule
- `app/models/prompts.py` — PromptTemplate
- `app/models/reports.py` — DailyReport
- `app/models/settings.py` — Settings (25+ columns, singleton pattern)
- `app/models/schema_version.py` — SchemaVersion
- `app/models/sentinel_state.py` — SentinelState

### Docker
- `Dockerfile` — Current CMD is `python -m flask --app app run ...` (needs migration step)
- `docker-compose.yml` — DATABASE_URL points to `/data/docksentinel.db`

### CLAUDE.md guidance
- `./CLAUDE.md` §Technology Stack — Alembic section with batch migration documentation links

### Research findings
- `.planning/research/PITFALLS.md` — SQLite-specific migration constraints

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/extensions.py`: `db` instance — Alembic env.py will import `db.metadata` from here
- `app/models/__init__.py`: Imports all models — ensures all tables registered with metadata for autogenerate

### Established Patterns
- **App factory**: `create_app()` in `app/__init__.py` handles all initialization — Alembic gating fits here
- **Environment-based config**: `DATABASE_URL` env var already used for DB location
- **TESTING flag**: Already checked in `create_app()` for coordinator startup — same pattern for `db.create_all()` gating

### Integration Points
- `create_app()` in `app/__init__.py` — where `db.create_all()` and `_ensure_settings_schema_compat()` are called
- `Dockerfile` CMD — needs pre-flight migration step
- Test fixtures in `tests/` — use `create_app()` with TESTING=True

</code_context>

<specifics>
## Specific Ideas

- CLAUDE.md explicitly recommends Alembic (not Flask-Migrate) with `render_as_batch=True` for SQLite
- The 8 columns in `_ensure_settings_schema_compat` all have NOT NULL defaults, so the batch migration must preserve those defaults
- Existing databases may or may not have these columns already (the compat function checks) — the Alembic revision needs to handle both cases gracefully

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-alembic-migration-infrastructure*
*Context gathered: 2026-04-05 via auto-mode*
