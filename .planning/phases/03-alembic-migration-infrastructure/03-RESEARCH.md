# Phase 3: Alembic Migration Infrastructure - Research

**Researched:** 2026-04-05
**Domain:** Alembic migrations, SQLite batch mode, Flask-SQLAlchemy integration
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Initialize Alembic with `render_as_batch=True` in `env.py` for SQLite compatibility (SQLite doesn't support most ALTER TABLE operations natively — batch mode recreates the table). Per MIG-01.
- **D-02:** `env.py` imports Flask-SQLAlchemy's `db.metadata` as the `target_metadata` so autogenerate can diff against the ORM models.
- **D-03:** `alembic.ini` sets `sqlalchemy.url` to empty — `env.py` reads `SQLALCHEMY_DATABASE_URI` from Flask app config or `DATABASE_URL` env var at runtime.
- **D-04:** Autogenerate the initial migration from current ORM models using `alembic revision --autogenerate -m "initial schema"`. This captures the complete current schema (all 7 tables) as the baseline.
- **D-05:** Existing v0.2 databases are stamped with `alembic stamp head` so Alembic treats them as current and doesn't try to re-create tables. Per MIG-02.
- **D-06:** The stamp operation is documented in README and handled in Docker entrypoint logic (if `alembic_version` table doesn't exist, stamp before upgrade).
- **D-07:** The 8 ALTER TABLE statements in `_ensure_settings_schema_compat` are converted to a single Alembic revision (revision 2) using `batch_alter_table('settings')` with `add_column()` for each of: `llm_transport`, `cli_backend`, `cli_timeout_seconds`, `cli_max_retries`, `dedup_window_seconds`, `container_rate_limit_count`, `container_rate_limit_window_seconds`, `keyword_flush_delay_lines`. Per MIG-03.
- **D-08:** The downgrade for revision 2 uses `batch_alter_table('settings')` with `drop_column()` for each of the 8 columns.
- **D-09:** After the Alembic revision is verified working, `_ensure_settings_schema_compat` is deleted from `app/__init__.py` and its call removed from `create_app()`.
- **D-10:** `db.create_all()` call in `create_app()` is gated behind `if app.config.get("TESTING")`. Tests continue to use `db.create_all()` via the test app factory — no change to test fixtures or logic. Per MIG-04.
- **D-11:** Production startup uses `alembic upgrade head` in the Docker CMD/entrypoint. The Dockerfile CMD is updated to run migrations before starting Flask.
- **D-12:** The `_seed_defaults()` function stays in `create_app()` (called after either `db.create_all()` in test or `alembic upgrade head` in production) — it seeds default data, not schema.

### Claude's Discretion

- Exact alembic directory structure (`alembic/` vs `migrations/`)
- Whether to use a shell script entrypoint or inline the migration command in Docker CMD
- Exact revision message wording
- Whether `_seed_defaults()` needs any adjustment for the new flow

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MIG-01 | Alembic initialized with render_as_batch=True for SQLite compatibility | D-01 to D-03; `render_as_batch` in `MigrationContext.configure()` enables batch mode for all operations |
| MIG-02 | Initial migration generated and existing databases stamped (alembic stamp head) | D-04 to D-06; `alembic stamp head` inserts the head revision into `alembic_version` without running migrations |
| MIG-03 | Hardcoded _ensure_settings_schema_compat ALTER TABLE statements replaced by Alembic revisions | D-07 to D-09; `batch_alter_table` with `add_column` handles the 8 column additions; downgrade uses `drop_column` |
| MIG-04 | db.create_all() gated to TESTING=True; production uses alembic upgrade head | D-10 to D-12; `app.config.get("TESTING")` already used in `create_app()` for coordinator; same pattern applies |
</phase_requirements>

---

## Summary

Phase 3 replaces the brittle `_ensure_settings_schema_compat()` function (8 hardcoded ALTER TABLE statements in `app/__init__.py` lines 82-103) with Alembic-managed schema evolution. The work has four concrete pieces: (1) initialize Alembic with SQLite batch mode configured in `env.py`, (2) generate a baseline "initial schema" migration from the existing 7 ORM models, (3) generate a second migration revision that encodes the 8 column additions as `batch_alter_table` operations with full downgrade support, and (4) gate `db.create_all()` to `TESTING=True` and update the Docker CMD to run `alembic upgrade head` before starting Flask.

The critical SQLite constraint is that `ALTER TABLE` is severely limited in SQLite — you cannot drop columns, rename columns, or change column types. Alembic's batch mode solves this by copying the table to a temp table, recreating it with the desired schema, copying data back, and dropping the original. This is enabled by setting `render_as_batch=True` in `env.py`'s `context.configure()` call, which makes autogenerate emit `with op.batch_alter_table(...)` rather than bare `op.add_column(...)` calls.

The existing test suite already uses `TESTING=True` via `monkeypatch.setenv("TESTING", "true")` in every `_build_app()` helper — no test file touches `_ensure_settings_schema_compat` directly, so the deletion is transparent to all 31 tests. The only behavioral change tests will observe is that `db.create_all()` is now conditioned on `TESTING=True`, which is exactly the state they already set.

**Primary recommendation:** Directory name `migrations/` (over `alembic/`) for better Python project conventions; shell script entrypoint over inline CMD chaining for legibility and error handling.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| alembic | 1.18.4 | Schema migration management | SQLAlchemy's official migration tool; already installed on this machine |
| SQLAlchemy | 2.0.36 | ORM (already in stack) | Alembic is built on top of SQLAlchemy — no separate install needed |
| Flask-SQLAlchemy | 3.1.1 | db instance and metadata (already in stack) | `db.metadata` is the target_metadata for autogenerate |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| alembic (CLI) | 1.18.4 | `alembic revision`, `alembic upgrade`, `alembic stamp` | Used during init (one-time) and in Docker entrypoint (every boot) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Plain alembic | Flask-Migrate | Flask-Migrate is a thin CLI wrapper; adds Flask app context dependency at migration time. CLAUDE.md explicitly rejects Flask-Migrate — use plain Alembic. |
| `migrations/` directory | `alembic/` directory | Convention only; `alembic/` is Alembic's default. `migrations/` is cleaner for multi-tool projects. Either works — discretion area. |

**Installation:**
```bash
# Alembic is already installed on this machine (1.18.4)
# Add to requirements.txt:
alembic==1.18.4
```

**Version verification:** Alembic 1.18.4 confirmed installed (`alembic --version`). This is the current latest version available on this machine and should be pinned in requirements.txt.

---

## Architecture Patterns

### Recommended Project Structure

```
DockSentinel/
├── migrations/              # Alembic root (discretion: alembic/ also acceptable)
│   ├── alembic.ini          # NOT here — alembic.ini lives at project root
│   ├── env.py               # Connects Alembic to Flask app + db.metadata
│   ├── script.py.mako       # Migration file template (alembic default)
│   └── versions/
│       ├── 0001_initial_schema.py        # Revision 1: baseline from autogenerate
│       └── 0002_settings_compat_cols.py  # Revision 2: 8 columns from _ensure_settings_schema_compat
├── alembic.ini              # Lives at project root (where alembic CLI is run)
├── app/
│   ├── __init__.py          # create_app() — db.create_all() gated, _ensure_settings_schema_compat deleted
│   ├── extensions.py        # db instance — imported by env.py
│   └── models/
│       └── __init__.py      # Imports all models — imported by env.py to register metadata
├── docker-entrypoint.sh     # NEW: runs alembic upgrade head then exec flask
└── Dockerfile               # CMD updated to use entrypoint script
```

### Pattern 1: Alembic env.py for Flask-SQLAlchemy (Offline + Online modes)

**What:** The `env.py` file must import `db.metadata` from the Flask app to make autogenerate work. It must also push an app context so Flask-SQLAlchemy's `db` object can resolve the database URL.

**When to use:** Required for any Flask-SQLAlchemy + Alembic integration.

**Example:**
```python
# migrations/env.py
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import db and all models so metadata is populated
from app.extensions import db
import app.models  # noqa: F401 — registers all models with db.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db.metadata


def get_url() -> str:
    # Priority: alembic.ini sqlalchemy.url → DATABASE_URL env var → fallback
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    return os.environ.get("DATABASE_URL", "sqlite:///./data/docksentinel.db")


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # REQUIRED for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # REQUIRED for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### Pattern 2: Revision 2 — batch_alter_table for 8 settings columns

**What:** The `_ensure_settings_schema_compat` columns must be encoded as a proper Alembic revision with both upgrade and downgrade paths using `batch_alter_table`.

**When to use:** Any SQLite column addition/removal.

**Example:**
```python
# migrations/versions/0002_settings_compat_cols.py
"""add settings compat columns

Revision ID: <autogenerated>
Revises: <rev1_id>
Create Date: <autogenerated>
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = "<autogenerated>"
down_revision: str = "<rev1_id>"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("llm_transport", sa.String(16), nullable=False, server_default="api"))
        batch_op.add_column(sa.Column("cli_backend", sa.String(64), nullable=False, server_default="codex"))
        batch_op.add_column(sa.Column("cli_timeout_seconds", sa.Integer(), nullable=False, server_default="120"))
        batch_op.add_column(sa.Column("cli_max_retries", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("dedup_window_seconds", sa.Integer(), nullable=False, server_default="300"))
        batch_op.add_column(sa.Column("container_rate_limit_count", sa.Integer(), nullable=False, server_default="10"))
        batch_op.add_column(sa.Column("container_rate_limit_window_seconds", sa.Integer(), nullable=False, server_default="3600"))
        batch_op.add_column(sa.Column("keyword_flush_delay_lines", sa.Integer(), nullable=False, server_default="5"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("keyword_flush_delay_lines")
        batch_op.drop_column("container_rate_limit_window_seconds")
        batch_op.drop_column("container_rate_limit_count")
        batch_op.drop_column("dedup_window_seconds")
        batch_op.drop_column("cli_max_retries")
        batch_op.drop_column("cli_timeout_seconds")
        batch_op.drop_column("cli_backend")
        batch_op.drop_column("llm_transport")
```

**Critical note:** `server_default` (not `default`) is used in migrations. `default` is a Python-side SQLAlchemy default; `server_default` is the DDL-level column default that SQLite sets when the migration runs. For NOT NULL columns being added to existing tables, `server_default` is mandatory — without it the migration fails on any row already in the table.

### Pattern 3: Idempotent Docker Entrypoint

**What:** The Docker CMD is changed from a direct Flask invocation to a shell script that stamps existing databases (if no `alembic_version` table), then runs `alembic upgrade head`, then starts Flask.

**When to use:** Any containerized Alembic workflow.

**Example:**
```bash
#!/bin/sh
# docker-entrypoint.sh
set -e

# If this is an existing v0.2 database (no alembic_version table), stamp it
# so Alembic doesn't try to re-create tables that already exist
python - <<'PYEOF'
import os, sqlite3

db_url = os.environ.get("DATABASE_URL", "")
if db_url.startswith("sqlite:////"):
    db_path = db_url[len("sqlite:////"):]
    if os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        if "settings" in tables and "alembic_version" not in tables:
            import subprocess
            subprocess.run(["alembic", "stamp", "head"], check=True)
PYEOF

alembic upgrade head

exec python -m flask --app app run --host 0.0.0.0 --port 5000
```

**Alternative (discretion):** Inline in Dockerfile CMD using `sh -c`. Shell script is preferred for readability and allows `set -e` for proper error propagation.

### Pattern 4: Gating db.create_all() in create_app()

**What:** The existing `db.create_all()` and `_ensure_settings_schema_compat()` calls are replaced with a conditional block.

**When to use:** Flask applications that use Alembic for production but need fast schema creation for tests.

**Example:**
```python
# app/__init__.py — create_app() schema init block (replaces lines 319-322)
with app.app_context():
    if app.config.get("TESTING"):
        db.create_all()
    _seed_defaults()

# _ensure_settings_schema_compat() function at lines 82-103: DELETE ENTIRELY
# Its call at line 321: DELETE
```

**Test compatibility proof:** Every test's `_build_app()` calls `monkeypatch.setenv("TESTING", "true")` before `create_app()`. `AppConfig.from_env()` reads `TESTING` from env, sets `config.testing = True`, which sets `app.config["TESTING"] = True`. The gated `db.create_all()` fires for all tests unchanged.

### Anti-Patterns to Avoid

- **Omitting `render_as_batch=True`:** Without this, `op.add_column()` on SQLite works for simple additions, but `op.drop_column()` and any column modification will raise `CompileError`. Setting it globally in both `run_migrations_offline` and `run_migrations_online` is correct — do not set it only in one branch.
- **Using `default=` instead of `server_default=` in revision upgrade():** `default` is ignored at DDL time; only `server_default` is emitted as SQL `DEFAULT`. On a table with existing rows and NOT NULL columns, missing `server_default` causes `IntegrityError`.
- **Importing Flask app object in env.py:** Do not import `create_app()` or the Flask `app` object in `env.py`. Import only `db` from `app.extensions` and `app.models` for side effects. Creating the full app in env.py pulls in all services, triggers coordinator startup, and creates circular dependency risks.
- **Running alembic upgrade inside create_app():** Production migrations belong in the Docker entrypoint, not inside `create_app()`. If `alembic upgrade head` runs inside `create_app()` it runs on every import, including test imports where `db.create_all()` is the schema source.
- **Checking "if column exists" in revision upgrade():** The existing `_ensure_settings_schema_compat` checks `if column_name not in existing_columns` before running each ALTER. An Alembic revision must NOT do this — Alembic's `alembic_version` table tracks which revisions have run; the revision will only execute once. Adding existence checks creates unmaintainable, non-standard migration code.
- **Autogenerating revision 2:** Do not use `--autogenerate` for revision 2. Autogenerate compares current ORM models against the database state — since the 8 columns are already in the ORM models and (for fresh databases) already in the schema from revision 1, autogenerate would detect no diff. Revision 2 must be hand-written.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQLite column modification | Custom ALTER TABLE + recreate logic | `op.batch_alter_table()` | Alembic batch handles FK constraints, index recreation, data copying — all edge cases covered |
| Migration version tracking | Custom `schema_version` table logic | `alembic_version` table (automatic) | SchemaVersion model in the codebase tracks app-level versioning; Alembic's own table is separate and managed automatically |
| Conditional stamping | Reading sqlite_master in Python to check for alembic_version | Shell script in entrypoint | One-time logic at startup; Python inline in entrypoint is acceptable but a dedicated shell function is cleaner |
| Database URL resolution | Hardcoding paths in alembic.ini | `env.py` reads `DATABASE_URL` env var | Same env var used by the Flask app — single source of truth; alembic.ini `sqlalchemy.url` stays empty |

**Key insight:** Alembic's `alembic_version` table is the single source of migration truth. The `SchemaVersion` ORM model already in the codebase serves a different purpose (app-level version display) and must be left untouched.

---

## Runtime State Inventory

> This phase involves replacing a runtime schema migration mechanism, so a targeted check is warranted.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `alembic_version` table: does NOT exist in v0.2 databases (Alembic has never run) | Docker entrypoint stamps existing databases before running `alembic upgrade head` |
| Live service config | None — no external services involved | None |
| OS-registered state | None | None |
| Secrets/env vars | `DATABASE_URL` env var — Alembic `env.py` reads this directly; no rename | None — `env.py` reads existing env var unchanged |
| Build artifacts | None — no compiled artifacts with migration logic | None |

**`_ensure_settings_schema_compat` runtime impact:** The function runs at every `create_app()` call in production. After deletion, the 8 columns it added are now guaranteed by Alembic revision 2. Existing databases that already have these columns will have the revision stamped (they won't re-run), so `alembic upgrade head` is a no-op for those columns on existing deployments.

---

## Common Pitfalls

### Pitfall 1: Autogenerate detects false diffs from SchemaVersion / SentinelState models

**What goes wrong:** Alembic autogenerate may flag the `schema_version` and `sentinel_state` tables as having diffs if their column definitions don't exactly match what SQLite stored. Common false positives include: server defaults quoted differently, nullable mismatch, index names.

**Why it happens:** Alembic's autogenerate compares ORM column definitions against reflected database schema. SQLite's schema reflection is imprecise — it doesn't always reflect `server_default` values or index names the same way the ORM defines them.

**How to avoid:** After running `alembic revision --autogenerate -m "initial schema"`, review the generated file before running it. Comment out any operations that shouldn't be there (e.g., `op.create_index` for an index that already exists). The goal of the initial migration is to represent the current state, not to modify anything.

**Warning signs:** Generated migration has `op.drop_index`, `op.alter_column`, or `op.create_index` for tables you haven't changed — these are false positives to investigate before applying.

### Pitfall 2: `server_default` vs `default` for NOT NULL columns

**What goes wrong:** `batch_op.add_column(sa.Column("llm_transport", sa.String(16), nullable=False, default="api"))` fails with `IntegrityError: NOT NULL constraint failed` on any table that has existing rows.

**Why it happens:** `default` in a Column definition is a Python-side SQLAlchemy default — it is not emitted as SQL `DEFAULT` in the DDL. When the migration runs against a table with existing rows, SQLite tries to fill the new NOT NULL column with NULL (since no `server_default` exists) and fails.

**How to avoid:** Use `server_default="api"` (string representation of the value, not Python literal) in all column definitions inside migration `upgrade()` functions. The model definition can keep `default="api"` — that's for Python-side ORM inserts, not migration DDL.

**Warning signs:** Migration works on a fresh empty database but fails on a database with at least one `settings` row.

### Pitfall 3: alembic.ini `script_location` path resolution

**What goes wrong:** `alembic upgrade head` fails with `FileNotFoundError` or `Can't locate revision` if `alembic.ini` uses a relative `script_location` and Alembic is run from a different working directory than expected.

**Why it happens:** `script_location = migrations` in `alembic.ini` resolves relative to the current working directory when `alembic` CLI is invoked. Docker entrypoints set `WORKDIR /app` — if the entrypoint `cd`s to a different directory, resolution breaks.

**How to avoid:** Set `WORKDIR /app` in Dockerfile. Run `alembic upgrade head` from `/app` (the project root). Confirm `alembic.ini` is at `/app/alembic.ini` and `script_location = migrations` resolves to `/app/migrations`. The entrypoint script should not `cd` away from `/app`.

**Warning signs:** `alembic upgrade head` works locally but fails in Docker container.

### Pitfall 4: Import side effects in env.py break test collection

**What goes wrong:** `pytest` fails to collect tests because `env.py` tries to create a Flask app or import services that require environment variables to be set.

**Why it happens:** If `env.py` calls `create_app()` to get the database URL from app config, all services initialize at import time, which requires `DATABASE_URL`, `SECRET_KEY`, etc.

**How to avoid:** `env.py` must only import `db` from `app.extensions` and `app.models` for metadata side effects. Get the database URL from `os.environ.get("DATABASE_URL")` directly — do not call `create_app()` in env.py.

**Warning signs:** `pytest tests/` starts failing after adding Alembic with errors about missing environment variables or circular imports.

### Pitfall 5: Revision 2 autogenerated instead of hand-written detects no changes

**What goes wrong:** Running `alembic revision --autogenerate -m "settings compat"` generates an empty migration with no `upgrade()` body because the 8 columns already exist in the ORM models and (for a fresh database) already exist from revision 1's initial schema.

**Why it happens:** Autogenerate is a diff tool — it compares what the ORM says the schema should be vs what the database currently has. Revision 1 captures the full current schema, so there is no diff for the settings columns.

**How to avoid:** Revision 2 must be created with `alembic revision -m "add settings compat columns"` (no `--autogenerate`) and hand-written with the explicit `batch_alter_table` additions. This revision represents the historical delta from v0.1 to v0.2 that `_ensure_settings_schema_compat` was patching.

---

## Code Examples

Verified patterns from Alembic 1.18.4 official documentation.

### alembic.ini (project root)
```ini
[alembic]
# Leave sqlalchemy.url empty — env.py reads DATABASE_URL from environment
script_location = migrations
file_template = %%(rev)s_%%(slug)s
prepend_sys_path = .
truncate_slug_length = 40

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

### Dockerfile CMD update
```dockerfile
# Before (current):
CMD ["python", "-m", "flask", "--app", "app", "run", "--host", "0.0.0.0", "--port", "5000"]

# After (with entrypoint script):
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh
CMD ["/app/docker-entrypoint.sh"]
```

### create_app() schema init change (lines 319-322 of app/__init__.py)
```python
# BEFORE (lines 319-322):
with app.app_context():
    db.create_all()
    _ensure_settings_schema_compat()
    _seed_defaults()

# AFTER:
with app.app_context():
    if app.config.get("TESTING"):
        db.create_all()
    _seed_defaults()

# Also DELETE the entire _ensure_settings_schema_compat() function (lines 82-103)
# and its call (line 321 shown above, already removed in AFTER block)
```

### Stamp operation for existing databases
```bash
# Run once against any existing v0.2 database to mark it as current
# (No migrations will execute — just records the revision in alembic_version table)
DATABASE_URL=sqlite:////data/docksentinel.db alembic stamp head

# Verify:
DATABASE_URL=sqlite:////data/docksentinel.db alembic current
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_ensure_settings_schema_compat()` — imperative check-then-alter | Alembic revision with batch_alter_table | This phase | Removes 22 lines of brittle schema patching; gains downgrade support and migration history |
| `db.create_all()` on every startup | `db.create_all()` gated to TESTING; `alembic upgrade head` in production entrypoint | This phase | Production schema is now version-controlled; no schema drift possible |

**Deprecated/outdated:**
- `_ensure_settings_schema_compat`: Deleted in this phase. Replaced by revision 2.
- Unconditional `db.create_all()` in `create_app()`: Gated to TESTING. Production uses alembic.

---

## Open Questions

1. **Does `_seed_defaults()` need adjustment when running in production (no db.create_all())?**
   - What we know: `_seed_defaults()` calls `Settings.singleton()`, `SchemaVersion.singleton()`, `SentinelState.singleton()` — all of which use `db.session.get(cls, 1)` and create the row if absent. After `alembic upgrade head`, the tables exist but are empty, so the singletons will be created on first call.
   - What's unclear: Whether `_seed_defaults()` is called reliably in the production path after `alembic upgrade head` runs in the entrypoint (outside Flask context) vs when Flask starts.
   - Recommendation: `_seed_defaults()` runs inside `with app.app_context():` in `create_app()`, which is called when Flask starts — this is AFTER the entrypoint runs `alembic upgrade head`. The sequence is correct: schema guaranteed by Alembic → Flask starts → `create_app()` → `_seed_defaults()` runs. No adjustment needed.

2. **What is the correct `script_location` if using `migrations/` vs `alembic/`?**
   - What we know: `script_location` in `alembic.ini` is a path relative to where `alembic` is invoked (project root in this case).
   - What's unclear: Which name to use — discretion area per CONTEXT.md.
   - Recommendation: Use `migrations/` — distinguishes Alembic artifacts from any future `alembic/` package that might exist; matches common Python project conventions.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| alembic CLI | MIG-01, MIG-02, MIG-03 — generate and run migrations | Yes | 1.18.4 | None needed |
| Python 3.12 | All | Yes | 3.12.7 | — |
| SQLAlchemy | Already in requirements.txt | Yes | 2.0.36 | — |
| Flask-SQLAlchemy | Already in requirements.txt | Yes | 3.1.1 | — |
| SQLite | Docker volume at /data/docksentinel.db | Bundled with Python | — | — |
| sh (POSIX shell) | Docker entrypoint script | Yes (python:3.12-slim base image) | — | Inline CMD with && chaining |

**Missing dependencies with no fallback:** None — all required tools are available.

**Note:** Alembic must be added to `requirements.txt` (it is installed on the dev machine but is not in the current `requirements.txt`). Without this, the Docker image will not have Alembic installed and `alembic upgrade head` will fail in the entrypoint.

---

## Sources

### Primary (HIGH confidence)
- Alembic 1.18.4 — SQLite batch migration docs: https://alembic.sqlalchemy.org/en/latest/batch.html
- Alembic 1.18.4 — `render_as_batch` in `context.configure()`: https://alembic.sqlalchemy.org/en/latest/api/runtime.html#alembic.runtime.migration.MigrationContext.configure
- Alembic 1.18.4 — autogenerate docs: https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- Alembic 1.18.4 — `stamp` command: https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.stamp
- `CLAUDE.md` §Technology Stack — Alembic section with explicit `render_as_batch=True` recommendation and batch migration link
- Direct code inspection: `app/__init__.py` lines 82-103 (`_ensure_settings_schema_compat`), lines 319-322 (create_app schema init), `app/extensions.py` (`db` instance), `app/models/__init__.py` (all model imports), `Dockerfile` (current CMD)
- Direct environment check: `alembic --version` → 1.18.4 confirmed; not in `requirements.txt` (confirmed by reading requirements.txt)

### Secondary (MEDIUM confidence)
- CLAUDE.md §Technology Stack §What NOT to Add — Flask-Migrate explicitly excluded
- Existing test pattern: All 10 test files use `monkeypatch.setenv("TESTING", "true")` before `create_app()` — confirmed by reading test_models.py and test_api.py fixtures

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — Alembic 1.18.4 verified installed; already in CLAUDE.md recommendations
- Architecture: HIGH — patterns derived from direct code inspection of files to be modified + official Alembic docs
- Pitfalls: HIGH — `server_default` vs `default` is a well-documented Alembic SQLite gotcha; others derived from code inspection

**Research date:** 2026-04-05
**Valid until:** 2026-06-05 (Alembic API is stable; SQLite behavior is stable)
