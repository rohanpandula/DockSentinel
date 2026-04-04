# Domain Pitfalls: Flask Monolith Refactoring

**Domain:** Flask/SQLAlchemy monolith refactored into layered architecture
**Codebase:** DockSentinel v0.2, ~3,309 LOC, 31 tests, SQLite, APScheduler
**Researched:** 2026-04-04
**Confidence:** HIGH (all pitfalls verified against official docs, known issues, or direct codebase inspection)

---

## Critical Pitfalls

Mistakes in this category cause test failures, runtime errors, or forced rewrites.

---

### Pitfall 1: Circular Imports When Splitting the App Factory

**What goes wrong:** Moving routes into blueprints or services into separate modules causes `ImportError: cannot import name 'X' from partially initialized module 'app'`. This happens when a new module does `from app import db` or `from app.models import Settings` and `app/__init__.py` is still mid-evaluation at that point.

**Why it happens:** The current `app/__init__.py` is 334 LOC that simultaneously defines the factory, imports every service, and registers web routes as closures. Any refactoring that creates new modules importing back into `app` before the factory finishes will trigger Python's circular import detection. This is especially likely during blueprint extraction because blueprints often need models immediately at module load time.

**Consequences:** All tests that call `create_app()` fail with ImportError. The app does not start at all.

**Prevention:**
- `db` already lives in `app/extensions.py` — always import from there, never from `app` or `app/__init__`.
- New blueprints import from `app.extensions` and `app.models.*`, never from `app` itself.
- Register blueprints inside `create_app()` using deferred local imports (as the codebase already does in `_register_api_blueprints`). Keep this pattern.
- New service modules must not import `create_app` or anything that causes `app/__init__` to be re-evaluated.

**Detection:** Import failures at module load, before any test even runs. If `pytest --collect-only` fails, this is the likely cause.

**Phase:** Blueprint extraction phase; any phase that adds new top-level modules.

---

### Pitfall 2: Orphaned App Context in Background Threads

**What goes wrong:** After moving service logic into separate classes or a DI container, a background thread (APScheduler job, `DockerWatcher` callback, health check loop) calls `db.session` without an active Flask app context. This produces `RuntimeError: Working outside of application context.` — often only in production under real Docker events, not in any test.

**Why it happens:** The current `coordinator.py` already wraps APScheduler and Docker callbacks with `with self.app.app_context()`. Any refactoring that moves these wrappers or introduces a new call site that touches SQLAlchemy models without keeping the context manager risks breaking this. Service-layer methods are especially risky: when you introduce `AnalysisEventRepository` or `SettingsRepository`, callers in background threads must still push an app context before calling them.

**Consequences:** Silent failure of nightly briefing, missed analysis events, and Docker log processing silently stops. No test will catch this because tests disable the coordinator.

**Prevention:**
- Treat the `with app.app_context()` wrapper as the boundary, not an implementation detail. Every entry point into SQLAlchemy from a non-request thread must have its own `with app.app_context():` block.
- When extracting service methods, do not move the app context push into the service itself — keep it at the scheduler/thread boundary in `coordinator.py`.
- Add an explicit integration test that exercises a service method in a background thread to catch this class of regression.

**Detection:** `RuntimeError: Working outside of application context` in logs, never reproduced in tests. Flask-SQLAlchemy's scoped session is thread-local; context is not inherited.

**Phase:** Service extraction, repository pattern introduction, and any phase that restructures the coordinator.

---

### Pitfall 3: Alembic "Initial Migration" Overwrites Live Database

**What goes wrong:** Running `alembic revision --autogenerate` for the first time against a live SQLite database that was created by `db.create_all()` generates an initial migration that wants to CREATE all tables. Applying it with `alembic upgrade head` then fails or drops data because Alembic thinks the tables do not exist yet.

**Why it happens:** Alembic uses its own `alembic_version` table to track state. A database created by `db.create_all()` has no `alembic_version` row, so Alembic treats it as empty. This is the standard trap for any app migrating from `db.create_all()` to Alembic.

**Consequences:** `alembic upgrade head` against a running production database will attempt to re-CREATE all tables. SQLite raises errors or silently no-ops depending on `IF NOT EXISTS` behavior. Existing data is not lost in SQLite's case, but the migration history is corrupt and future migrations will be unreliable.

**Prevention:**
1. Generate the initial migration normally (it will contain `op.create_table(...)` calls for all tables).
2. Before applying it, run `alembic stamp head` against the live database. This writes the current revision into `alembic_version` without executing any DDL, telling Alembic the schema is already at that state.
3. Remove or wrap the `_ensure_settings_schema_compat()` ADD COLUMN block in `app/__init__.py` only after verifying Alembic migration history covers all those columns.
4. Do not remove `_ensure_settings_schema_compat()` until Alembic is proven working across both a fresh DB and an existing DB.

**Detection:** `alembic upgrade head` succeeds but generates SQL containing `CREATE TABLE` against a database that already has those tables. Always dry-run with `--sql` flag first.

**Phase:** Migration phase (replacing hardcoded schema SQL with Alembic).

---

### Pitfall 4: Breaking the `app.extensions["services"]` Contract Before Tests Are Updated

**What goes wrong:** Tests directly mutate `app.extensions["services"]` to inject test doubles: `app.extensions["services"]["llm_client"] = DummyLLM()`. If the DI container migration renames or restructures this dict — for example, moving to a typed dataclass container — those test lines silently no longer replace the real dependency, causing tests to hit the real LLM client and fail in CI.

**Why it happens:** There are 4+ test files that use `app.extensions["services"][...]` to swap out collaborators. The dict key names are the public contract for the test harness. If the refactoring changes the container structure before updating all test fixtures, tests silently use the wrong dependency or fail with `KeyError`.

**Consequences:** Tests that were passing now either fail (KeyError) or pass with wrong behavior (the dummy was not injected, but the test happened to not care). This is the hardest regression to diagnose because it does not produce an obvious error message.

**Prevention:**
- When migrating from dict to a typed container, maintain the `app.extensions["services"]` dict as a shim that proxies to the typed container for one full phase. Do not remove the dict access until all test injection sites are updated.
- Audit every `app.extensions["services"]` reference before removing it. Run `grep -r 'extensions\["services"\]' tests/` to get the full list.
- A typed `ServiceContainer` dataclass makes injection cleaner: `app.extensions["services"].llm_client = DummyLLM()`.

**Detection:** Tests pass locally (where environment variables might differ) but produce unexpected behavior. Check injection sites explicitly when modifying the DI layer.

**Phase:** DI container / typed service injection phase.

---

### Pitfall 5: Settings Singleton Split Breaks Callers That Fetch It Mid-Request

**What goes wrong:** `Settings.singleton()` is called in 6+ places across sentinel.py, briefing.py, settings API, and the settings page. When the god object is split into `LLMConfig`, `AlertConfig`, etc., any call site that still calls `Settings.singleton()` gets the old unified object (if it still exists) or a `AttributeError` (if the field was moved). This is a cross-cutting refactor that has no single place to update.

**Why it happens:** The 25-field Settings model is used directly in service methods (`_settings()` in SentinelService, BriefingService), web routes (settings_page), and the settings API (`_ALLOWED_FIELDS` whitelist). All these callers access fields by name. Splitting the model requires updating every caller simultaneously or maintaining a facade.

**Consequences:** Partial splits leave some callers accessing non-existent attributes. The settings_page POST handler uses `hasattr(settings, key)` — if a field moves to a sub-model, `hasattr` returns False and updates silently fail. The `_ALLOWED_FIELDS` set in settings.py also needs updating.

**Prevention:**
- Keep the `Settings` SQLAlchemy model as the single DB-backed source of truth. Introduce domain config classes (`LLMConfig`, `AlertConfig`) as Pydantic read models populated from `Settings`, not as separate DB models.
- Migrate one config group at a time (LLM fields, then Alert fields, etc.) and update all callers of that group in the same commit.
- The settings_page's `hasattr`-based POST handler should be replaced with an explicit field whitelist at the same time as the split (the `_ALLOWED_FIELDS` pattern from the API is correct; apply it to the web route too).

**Detection:** Settings page silently drops updates for fields that moved. API returns stale values. Check with a before/after `GET /api/settings` comparison after each split step.

**Phase:** Settings decomposition phase.

---

## Moderate Pitfalls

Mistakes in this category cause behavioral regressions or test flakiness, but not hard failures.

---

### Pitfall 6: `expire_on_commit=False` Behavior Broken by Session Scoping Changes

**What goes wrong:** `app/extensions.py` sets `expire_on_commit=False` on the SQLAlchemy session. This is why models can be accessed after `db.session.commit()` without triggering a new SELECT. If refactoring introduces a repository pattern that creates its own session (rather than using the Flask-SQLAlchemy scoped session), that new session will default to `expire_on_commit=True`, causing `DetachedInstanceError` when view functions access model attributes after commit.

**Prevention:** Any new session factory or repository base class must explicitly set `expire_on_commit=False` to match the existing behavior, or — better — use the Flask-SQLAlchemy scoped session exclusively.

**Detection:** `DetachedInstanceError: Instance <AnalysisEvent> is not bound to a Session` in template rendering or JSON serialization after a database write.

**Phase:** Repository pattern introduction.

---

### Pitfall 7: Pipeline Stage Refactor Breaks the `process_chunk` Return Contract

**What goes wrong:** `SentinelService.process_chunk()` always returns an `AnalysisEvent` with a persisted `id`. Several tests assert on `event.status`, `event.classification`, `event.alert_sent`, and `event.id`. If decomposing `process_chunk` into pipeline stages (prefilter stage, dedup stage, LLM stage, alert stage) causes any stage to return early without persisting a row, tests that expect a persisted event will get `None` or an un-committed object.

**Prevention:** The pipeline stages must maintain the invariant: `process_chunk` always returns a committed `AnalysisEvent` regardless of which stage short-circuits. Any pipeline abstraction layer must pass through the event object, not replace it with a different return type.

**Detection:** `AssertionError: None is not an AnalysisEvent` in sentinel pipeline tests, or `event.id` is None (uncommitted).

**Phase:** SentinelService pipeline decomposition phase.

---

### Pitfall 8: Alembic `env.py` Not Configured for In-Memory Test Database

**What goes wrong:** Once Alembic is introduced, tests that create a fresh SQLite database (via `create_app()` with `DATABASE_URL=sqlite:///...tmp...`) need to decide: use `db.create_all()` (fast, no migration) or `alembic upgrade head` (slow, migration-tested). If `create_app()` still calls `db.create_all()` after Alembic is introduced, the migration history is never exercised by tests. If `create_app()` is changed to run Alembic migrations instead, tests become slower and break on any migration error.

**Prevention:** Keep `db.create_all()` in the test-only code path (controlled by `app.config["TESTING"]`). Alembic migrations are exercised separately in a dedicated migration smoke-test, not in every unit test. This is the pattern that minimizes blast radius.

**Detection:** Test suite takes >10x longer after migration phase, or tests fail because `alembic upgrade head` hits a network/filesystem issue in CI.

**Phase:** Alembic migration phase.

---

### Pitfall 9: The `current_app` Proxy Failing Inside Services

**What goes wrong:** Service classes (SentinelService, BriefingService) currently use `db.session` directly and receive collaborators via constructor injection. If any refactored service method uses `current_app.extensions["services"]` to fetch a collaborator (e.g., a service calling another service via the app's service locator), it will fail when called from a background thread that has an app context but no active request context, because `current_app` proxies are request-context-aware.

**Prevention:** Services must never access `current_app` internally. Dependencies are injected at construction time or passed as method arguments. `current_app` belongs only in request handlers (blueprints) and the coordinator's thread boundary callbacks.

**Detection:** `RuntimeError: Working outside of request context` in scheduler logs when `_run_nightly_job` is executed.

**Phase:** Any phase that touches service internals or introduces inter-service calls.

---

### Pitfall 10: Pydantic v2 Model Used as SQLAlchemy Column Type

**What goes wrong:** When adding Pydantic request/response schemas to API endpoints, there is a temptation to reuse the Pydantic model directly as a SQLAlchemy column type or to make the SQLAlchemy model extend `BaseModel`. Pydantic v2 `BaseModel` is not compatible with Flask-SQLAlchemy's `db.Model` (which extends SQLAlchemy's `DeclarativeBase`). Attempting to inherit from both causes `TypeError` at class definition time.

**Why it matters here:** `VerdictParser` already uses Pydantic v2 (`app/services/verdict_parser.py`). The pattern of "Pydantic for validation, SQLAlchemy for persistence" is established and correct. The pitfall is in departing from it.

**Prevention:** Keep Pydantic schemas as separate classes (`SettingsResponse`, `InsightQueryParams`, etc.). Populate them from SQLAlchemy models using `model_validate(settings.as_dict(), from_attributes=True)` or by constructing them from the model's `as_dict()`. Never subclass both `BaseModel` and `db.Model`.

**Detection:** `TypeError: metaclass conflict` at import time.

**Phase:** Pydantic request/response validation phase.

---

## Minor Pitfalls

Low probability or low severity, but worth noting.

---

### Pitfall 11: Blueprint URL Prefix Collision With Existing Web Routes

**What goes wrong:** The existing `_register_web_routes` function registers routes without a prefix (`/dashboard`, `/settings`, `/exclusions`, etc.). If web routes are migrated to a Blueprint with a url_prefix, the prefix must remain empty or Flask will 404 on all UI routes. The Jinja2 templates use `url_for("dashboard")`, `url_for("settings_page")` etc. — these function names must remain unchanged after blueprint extraction, or all template redirects break.

**Prevention:** When registering a web routes blueprint, use `url_prefix=""` and ensure the endpoint names (second argument to `@bp.get`) match the existing function names used in `url_for()` calls.

**Detection:** All UI pages return 404 after blueprint extraction. Check `flask routes` output before and after.

**Phase:** Web route blueprint extraction.

---

### Pitfall 12: Docker `non-root user` Breaking SQLite File Permissions

**What goes wrong:** Adding a non-root user to the Dockerfile (a security best practice) can cause the SQLite file at `data/docksentinel.db` to be inaccessible if the `data/` volume is owned by root from a previous container run. The new non-root user cannot write to it, and the app fails to start silently or with a cryptic SQLAlchemy error.

**Prevention:** Set the volume mount to be owned by the non-root UID in the Compose file using `user:` directive consistently. Alternatively, `chown` the data directory in the Dockerfile entrypoint. Test by running a fresh `docker-compose up` after adding the non-root user, not just restarting an existing container.

**Detection:** `OperationalError: unable to open database file` in container logs after Docker hardening changes.

**Phase:** Docker hardening phase.

---

### Pitfall 13: Coverage Measurement Inflated by `create_app` Being Called Per-Test

**What goes wrong:** Every test file calls `create_app()` in its own `_build_app()` helper. Since `create_app()` runs `db.create_all()` and `_seed_defaults()`, those lines appear covered even without a dedicated test for that logic. When coverage is measured for the first time as part of the 80%+ goal, the apparent coverage will be inflated by app-factory startup paths, hiding genuinely untested service logic.

**Prevention:** Configure pytest-cov to exclude `app/__init__.py`'s `_seed_defaults` and `_ensure_settings_schema_compat` from line coverage — or write an explicit test for them. The actual coverage target should be measured against service and API modules, not the factory.

**Detection:** `coverage report` shows 90%+ on `app/__init__.py` despite having no dedicated factory tests.

**Phase:** Test coverage improvement phase.

---

## Phase-Specific Warning Summary

| Phase Topic | Likely Pitfall | Mitigation |
|---|---|---|
| Blueprint extraction (web routes) | Circular imports; url_for endpoint name changes | Import from `app.extensions`, not `app`; preserve endpoint function names |
| Alembic introduction | Initial migration overwrites live DB schema | Use `alembic stamp head` before first `upgrade head` on existing DB |
| Repository pattern | DetachedInstanceError; test injection sites broken | Match `expire_on_commit=False`; update all test double injection points |
| Settings decomposition | Silent POST failures; partial attribute access | Facade pattern; migrate field groups atomically with caller updates |
| Service DI container | `app.extensions["services"]` test contract broken | Keep dict shim until all test sites migrated |
| SentinelService pipeline | `process_chunk` return contract violated | All pipeline stages must return a committed `AnalysisEvent` |
| Background thread refactor | App context orphaned; `current_app` proxy fails | Context push stays at coordinator boundary; services never use `current_app` |
| Pydantic validation layer | BaseModel/db.Model metaclass conflict | Keep Pydantic schemas separate from SQLAlchemy models always |
| Docker hardening | SQLite file permission failure on non-root user | Test fresh `docker-compose up` after UID changes |
| Coverage measurement | Inflated by app factory startup paths | Measure coverage on service/API modules specifically |

---

## Sources

- Flask Application Context — Flask-SQLAlchemy Documentation: https://flask-sqlalchemy.readthedocs.io/en/stable/contexts/
- Flask Mega-Tutorial Part XV: Better Application Structure (Miguel Grinberg): https://blog.miguelgrinberg.com/post/the-flask-mega-tutorial-part-xv-a-better-application-structure
- Alembic Tutorial (official): https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Initialize Alembic on Existing Database (Medium): https://medium.com/@megablazikenabhishek/initialize-alembic-migrations-on-existing-database-for-auto-generated-migrations-zero-state-31ee93632ed1
- APScheduler + Flask app context issue tracker: https://github.com/viniciuschiele/flask-apscheduler/issues/240
- flask-apscheduler Flask context example: https://github.com/viniciuschiele/flask-apscheduler/blob/master/examples/flask_context.py
- Architecture Patterns with Python — Repository Pattern (O'Reilly): https://www.cosmicpython.com/book/chapter_02_repository.html
- Flask-SQLAlchemy scoped_session scopefunc issue: https://github.com/pallets-eco/flask-sqlalchemy/issues/944
- Avoiding circular imports in Flask and SQLAlchemy: https://www.homedutech.com/faq/python/how-to-avoid-circular-imports-in-flask-and-sqlalchemy.html
- Best Practices for Alembic and SQLAlchemy (DEV Community): https://dev.to/welel/best-practices-for-alembic-and-sqlalchemy-3b34
