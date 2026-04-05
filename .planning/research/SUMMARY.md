# Project Research Summary

**Project:** DockSentinel — Flask/SQLAlchemy/Pydantic v2 Architectural Refactor
**Domain:** Flask monolith refactoring — layered architecture, repository pattern, migration infrastructure
**Researched:** 2026-04-04
**Confidence:** HIGH

## Executive Summary

DockSentinel is a ~3,300 LOC Flask AIOps agent that monitors Docker container logs with LLM-powered analysis and alerting. The codebase is functionally correct but structurally compromised: business logic lives in the app factory, LLM invocation code is triplicated across three files, raw SQLAlchemy queries are scattered through service methods, and schema evolution is handled by eight hardcoded `ALTER TABLE` statements that run on every startup. The refactor milestone is not a rewrite — it is an incremental layering of well-established patterns (repository, service layer, typed DI container, Alembic migrations) onto a working codebase with zero framework changes and minimal new dependencies.

The recommended approach is a five-phase incremental delivery ordered by dependency and blast radius: extract `LLMCallService` first (largest duplication, no schema impact), wire the typed service container second (enables everything downstream), introduce the repository layer third (isolates DB access), set up Alembic fourth (eliminates brittle startup SQL), then add service decomposition, Pydantic validation, and pagination in a final cleanup pass. Each phase produces a green test suite before the next begins. This ordering is derived directly from the feature dependency graph in FEATURES.md and the phase structure in ARCHITECTURE.md — it is not arbitrary.

The primary risk in this refactor is invisible regressions caused by changing wiring without updating test injection sites. Four of the five critical pitfalls identified in PITFALLS.md are variations of this theme: circular imports during blueprint extraction, app context orphaned in background threads, the DI container test contract silently broken, and `Settings.singleton()` callers left pointing at stale fields. The mitigation in every case is the same: make changes incrementally within a single PR per phase step, verify the test suite is green at each step, and maintain shim compatibility layers until all consumer sites are updated.

## Key Findings

### Recommended Stack

The existing stack (Flask 3.0.3, SQLAlchemy 2.0.36, Pydantic 2.10.6, pytest 8.3.4, APScheduler 3.10.4) is retained without framework changes. Only two new production dependencies are added: `alembic==1.18.4` for migration management and `Flask-Pydantic==0.14.0` for request/response validation. One dev dependency is added: `pytest-cov==7.1.0` for coverage measurement. All architectural patterns — repository, service layer, typed DI container, config dataclasses, alert strategy abstraction — are implemented with Python stdlib or existing dependencies. Total new production dependency count: 2.

Optional safe version bumps are available (Flask 3.1.3, SQLAlchemy 2.0.49, Pydantic 2.12.5) but are not required for the refactor to succeed and should be deferred until tests are green.

**Core technologies:**
- `alembic==1.18.4`: Migration management — replaces 8 hardcoded `ALTER TABLE` statements; requires `render_as_batch=True` for SQLite compatibility
- `Flask-Pydantic==0.14.0`: Request/response validation — extends existing Pydantic v2 usage to HTTP boundaries via `@validate` decorator; pallets-eco fork with confirmed Pydantic v2 support
- `pytest-cov==7.1.0`: Coverage measurement — establishes the 80%+ quality gate; dev-only dependency
- Repository pattern: Pure Python classes wrapping SQLAlchemy sessions — no new library; pattern sourced from Architecture Patterns with Python (Cosmic Python)
- Typed `ServiceContainer` dataclass: Replaces `app.extensions["services"]` string-keyed dict — 10-line dataclass, no DI framework needed
- `AlertStrategy` Protocol: `abc.ABC` or `typing.Protocol` interface for alert channel abstraction — stdlib only, creates seam for future Slack/email channels

### Expected Features

The "user" for this refactor is the next developer working on the codebase. All table stakes features are structural repairs with direct code evidence; differentiators are quality improvements.

**Must have (table stakes):**
- Eliminate triplicated `_call_llm` / `_settings` / `_prompt` methods — bug fixes currently require 3 edits; evidence at `sentinel.py:92–122`, `briefing.py:25–56`, `settings.py:63–98`
- Replace `app.extensions["services"]` dict with typed container — typos in string keys fail at runtime, not import time
- Move web routes out of `create_app()` into a Blueprint — 150+ LOC of nested route closures in the app factory blocks isolated testing
- Replace `_ensure_settings_schema_compat` `ALTER TABLE` calls with Alembic — 8 unversioned, non-reversible DDL statements run on every startup
- Break `Settings` god object into domain-specific config classes — 25+ unrelated fields prevent scope-limited service dependencies
- Repository pattern for `AnalysisEvent` queries — 5 inline ORM queries scattered across `SentinelService` and web routes
- Increase test coverage to 80%+ with integration tests — current 31 tests at ~40–50% coverage, no end-to-end pipeline test
- Docker hardening (non-root user, health check) — running as root is a security baseline violation

**Should have (differentiators):**
- Pydantic v2 request/response schemas on list endpoints — makes API self-documenting and catches serialization regressions
- API pagination on `GET /api/insights` — current hard-limit of 200 rows will be a breaking change when the React SPA (ROADMAP Phase 1) arrives
- `AlertStrategy` abstraction (Telegram + future Slack/email) — minimal seam for ROADMAP Phase 3 alert channels
- Shared `conftest.py` fixtures — removes ~120 LOC of duplication across 10 test files
- Coverage gate in CI (`pytest --cov --cov-fail-under=80`) — prevents regression after refactor stabilizes

**Defer (v2+):**
- `SentinelService` pipeline decomposition into composable stage objects — high complexity; requires careful mapping of `LogBuffer` state and DB session sharing before decomposing; flag for a dedicated research spike
- SQLite to PostgreSQL migration — out of scope; no user-visible benefit at single-host scale
- Cursor/keyset pagination — overkill at current data volume; offset pagination is appropriate for thousands of events
- GraphQL API — fewer than 10 endpoints; REST serves the planned React SPA adequately
- Event sourcing for pipeline stages — synchronous single-process loop; message broker overhead is not justified

### Architecture Approach

The target is a strict four-layer architecture: Presentation (Flask Blueprints) → Service Layer → Repository Layer → Infrastructure/Models. No layer skips a level. The refactor enforces this boundary by creating a new `app/repositories/` directory for all SQLAlchemy queries, a new `app/services/llm_call.py` for the extracted `LLMCallService`, a new `app/web/routes.py` Blueprint for web routes, domain-specific frozen config dataclasses under `app/config_objects/`, and a `ServiceContainer` dataclass in `app/container.py`. The `Settings` SQLAlchemy ORM model keeps all 25+ columns — the DB schema does not change. Config splitting happens at the read boundary via factory functions that convert a `Settings` row into typed frozen dataclasses.

**Major components:**
1. `LLMCallService` — single point of LLM invocation; replaces triplicated `_call_llm` logic across three files; accepts `LLMConfig` dataclass; returns `LLMResult`
2. `AnalysisEventRepository` — owns all 6+ ORM queries currently scattered across `SentinelService`, `BriefingService`, and web route handlers; exposes named domain-query methods (`recent_by_hash`, `count_recent_by_container`, `list_paginated`)
3. `ServiceContainer` — typed `@dataclass` built once in `create_app()`; stored as `app.extensions["services"]`; all route handlers access services via typed attributes, not string keys
4. `AlertService` + `AlertStrategy` Protocol — extracts `_send_alert_if_allowed` from `SentinelPipeline`; cooldown/rate-limit logic stays in `AlertService`; Telegram transport behind the strategy interface
5. `Web Blueprint` — extracts 9 route closures from `_register_web_routes` into `app/web/routes.py`; zero URL or endpoint name changes; url_prefix remains empty
6. Alembic migrations — replaces `_ensure_settings_schema_compat`; `db.create_all()` gated to `TESTING=True`; `alembic upgrade head` runs in Docker entrypoint before Gunicorn

### Critical Pitfalls

1. **Circular imports during blueprint extraction** — always import `db` from `app.extensions`, never from `app` or `app.__init__`; register blueprints inside `create_app()` with deferred local imports (existing pattern in `_register_api_blueprints`); if `pytest --collect-only` fails before any test runs, this is the cause
2. **Alembic initial migration overwrites live database** — run `alembic stamp head` against the existing DB before the first `alembic upgrade head`; dry-run with `--sql` flag; do not delete `_ensure_settings_schema_compat` until migrations are proven on both fresh and existing DBs
3. **`app.extensions["services"]` test contract silently broken** — maintain the dict as a shim proxying to the typed container for one full phase; audit all `grep -r 'extensions\["services"\]' tests/` sites before removing; typed container makes injection cleaner (`container.llm_client = DummyLLM()`) once migrated
4. **App context orphaned in background threads** — the `with app.app_context()` wrapper must stay at the `coordinator.py` scheduler/thread boundary, never move into service internals; services must never use `current_app`; add an explicit integration test for background thread DB access
5. **Settings decomposition silently drops POST updates** — keep `Settings` ORM model as single DB-backed source of truth; migrate one config field group at a time with all callers updated in the same commit; replace `hasattr`-based POST handler with explicit field whitelist at the same time as the split

## Implications for Roadmap

Based on research, the feature dependency graph, the architectural phase ordering in ARCHITECTURE.md, and the pitfall phase warnings in PITFALLS.md, the following phase structure is recommended:

### Phase 1: Foundation — Service Extraction and DI Container
**Rationale:** `LLMCallService` extraction is the highest-leverage single change with the lowest blast radius — no schema changes, no test fixture changes, immediate deduplication of 120+ LOC. The typed `ServiceContainer` follows immediately because it unblocks all downstream dependency injection. Config dataclass decomposition completes this phase. None of these three steps touch the database, making them safe to do in parallel PRs.
**Delivers:** Unified LLM invocation, typed dependency access throughout the app, domain-scoped config objects. Test suite stays green.
**Addresses:** Triplicated `_call_llm`, string-keyed `app.extensions["services"]` dict, `Settings` god object (code layer only — DB schema unchanged)
**Avoids:** Pitfall 4 (breaking test injection contract) — shim maintained; Pitfall 5 (Settings split) — DB schema untouched in this phase
**Research flag:** Standard patterns — skip `/gsd:research-phase`

### Phase 2: Repository Layer
**Rationale:** Repositories must exist before services can be cleanly wired to them. This phase isolates all DB access behind named query methods, making service logic testable without a full ORM fixture. The incremental approach is copy-then-delete: create repository classes, wire them into one service at a time, verify tests green at each step.
**Delivers:** `AnalysisEventRepository`, `SettingsRepository`, `PromptRepository`, `ReportRepository`, `ExclusionRepository` — all ORM queries centralised; `SentinelPipeline`, `BriefingService`, and web routes wired to repositories
**Addresses:** 5 inline ORM queries in `SentinelService`, scattered queries in `BriefingService` and web route handlers
**Avoids:** Pitfall 6 (`expire_on_commit=False` must be preserved in repository session handling); Pitfall 1 (circular imports when creating new modules)
**Research flag:** Standard patterns — skip `/gsd:research-phase`

### Phase 3: Alembic Migration Infrastructure
**Rationale:** Alembic introduction must come after repositories exist so the migration test path is clean and the `SettingsRepository` can be verified against migrated schemas. The critical sequence is: generate initial migration, run `alembic stamp head` against the live DB, then convert `_ensure_settings_schema_compat` column-by-column into Alembic revisions, then delete the function.
**Delivers:** Alembic migration history, `_ensure_settings_schema_compat` deleted from `create_app()`, `db.create_all()` gated to `TESTING=True`, Docker entrypoint runs `alembic upgrade head`
**Addresses:** 8 unversioned `ALTER TABLE` statements running on every startup; no reversible migration path
**Avoids:** Pitfall 3 (initial migration overwriting live DB — use `stamp head`); Pitfall 8 (Alembic/test DB path conflict — keep `db.create_all()` for `TESTING=True`)
**Research flag:** Standard patterns — Alembic docs are authoritative; skip `/gsd:research-phase`

### Phase 4: Service Decomposition and Blueprint Extraction
**Rationale:** Service decomposition (AlertService, web Blueprint) comes after the repository layer is wired because `AlertService` depends on `AnalysisEventRepository`. Web Blueprint extraction is independent but grouped here as the remaining structural work before quality improvements.
**Delivers:** `AlertService` with `TelegramAlertStrategy`, web routes in `app/web/routes.py` Blueprint, `app/__init__.py` reduced to ~80 LOC of pure wiring
**Addresses:** `_send_alert_if_allowed` embedded in `SentinelPipeline`, 9 route closures in app factory, seam for future Slack/email alert channels
**Avoids:** Pitfall 11 (Blueprint URL prefix collision — `url_prefix=""` and preserve endpoint function names); Pitfall 2 (app context orphaned in background threads)
**Research flag:** Standard patterns — skip `/gsd:research-phase`. Exception: if `SentinelService` full pipeline decomposition (deferred to v2+) is reconsidered, flag that task for a dedicated spike.

### Phase 5: Pydantic Validation, Pagination, and Quality Gate
**Rationale:** Pydantic schemas and pagination are the final layer added on top of the stabilised repository and service layers. Coverage tooling closes the loop by establishing a measurable 80%+ gate that validates the refactor's completeness. Docker hardening is independent of everything and can be done in this phase or Phase 1 as a low-risk parallel task.
**Delivers:** Pydantic request/response schemas on API endpoints, offset pagination on `GET /api/insights` and `GET /api/reports`, shared `conftest.py` fixtures, `pytest-cov` with 80%+ gate, Docker non-root user + health check
**Addresses:** No API contract for list endpoints (breaking change risk when React SPA arrives), ~40–50% test coverage with no gate, Docker security baseline
**Avoids:** Pitfall 10 (Pydantic BaseModel/db.Model metaclass conflict — schemas are separate classes, populated via `model_validate`); Pitfall 12 (non-root Docker user breaking SQLite file permissions — test fresh `docker-compose up`); Pitfall 13 (coverage inflated by app factory startup paths — measure against service/API modules)
**Research flag:** Flask-Pydantic v0.14.0 Pydantic v2 compatibility is MEDIUM confidence (inferred from GitHub PR history). If integration behaves unexpectedly, fall back to manual `request.get_json()` + `model_validate()` inline — same result, slightly more boilerplate.

### Phase Ordering Rationale

- `LLMCallService` first because it has zero schema impact and immediately proves the service extraction approach before anything structural is touched
- `ServiceContainer` immediately follows because the typed container is the prerequisite for all repository injection downstream
- Repository layer before Alembic because the migration test path needs stable query methods to verify schema changes cleanly
- Alembic after repositories but before service decomposition so that `AlertService` (which depends on `AnalysisEventRepository`) can be wired to a migration-managed schema
- Pydantic validation and pagination last because they depend on stable repository query methods (`list_paginated`) that must exist before pagination can be implemented
- Docker hardening is independent and can be threaded into Phase 1 or Phase 5 based on availability

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 4 (SentinelService pipeline decomposition, if reconsidered from v2+ deferral):** The interaction between `LogBuffer` state, DB session scope, and `Settings` singleton access across pipeline stages is non-obvious. Requires mapping current state ownership before decomposing. Flag for a dedicated research spike if added to scope.
- **Phase 5 (Flask-Pydantic v0.14.0):** MEDIUM confidence on Pydantic v2 compatibility. Validate the `@validate` decorator behavior in a branch test before committing to it across all endpoints.

Phases with standard patterns (skip `/gsd:research-phase`):
- **Phase 1 (LLMCallService + ServiceContainer + config dataclasses):** Mechanical extraction; Cosmic Python patterns; well-documented
- **Phase 2 (Repository layer):** Repository pattern is thoroughly documented in Cosmic Python and SQLAlchemy community sources
- **Phase 3 (Alembic):** Official Alembic docs cover the exact `stamp head` → `upgrade head` → delete `db.create_all()` sequence
- **Phase 4 (AlertService + Web Blueprint):** Strategy pattern and Blueprint extraction are both well-documented; no novel integration

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library versions verified on PyPI 2026-04-04; Alembic and pytest-cov are official tools; Flask-Pydantic is MEDIUM (Pydantic v2 compat inferred from PR history, not direct test) |
| Features | HIGH | Grounded in direct codebase inspection with line-number evidence; all table stakes features have concrete code references |
| Architecture | HIGH | Patterns sourced from Architecture Patterns with Python (O'Reilly); Flask documentation; direct data flow tracing through codebase |
| Pitfalls | HIGH | All pitfalls verified against official docs, known issue trackers, or direct codebase inspection; phase mapping is precise |

**Overall confidence:** HIGH

### Gaps to Address

- **Flask-Pydantic v0.14.0 Pydantic v2 compatibility:** Confidence is MEDIUM. Validate with a minimal integration test before full adoption. Fallback is manual `request.get_json()` + `model_validate()` — functionally equivalent with more boilerplate. Resolve in Phase 5.
- **SentinelService pipeline decomposition complexity:** Research explicitly deferred this to v2+ and flagged it for a spike. If the roadmap includes it, run `/gsd:research-phase` on the `LogBuffer` + session + settings interaction before planning that phase.
- **Coverage baseline:** The current ~40–50% estimate is unverified (no tooling). Actual coverage may be lower once factory startup inflation is excluded. The 80%+ target may require more integration tests than Phase 5 allocates. Address by running `pytest-cov` as the first action of Phase 5 to establish the real baseline before setting the threshold.

## Sources

### Primary (HIGH confidence)
- Architecture Patterns with Python (Cosmic Python) — https://www.cosmicpython.com/ — repository pattern, service layer, dependency injection, composition root
- Alembic 1.18.4 official documentation — https://alembic.sqlalchemy.org/ — batch migrations for SQLite, autogenerate, stamp head procedure
- Flask official documentation — https://flask.palletsprojects.com/ — blueprint patterns, app context, extensions
- Flask-SQLAlchemy documentation — https://flask-sqlalchemy.readthedocs.io/ — scoped session, app context in background threads
- PyPI (all versions verified 2026-04-04) — alembic, flask, sqlalchemy, pydantic, pytest-cov, flask-pydantic

### Secondary (MEDIUM confidence)
- Flask-Pydantic GitHub (pallets-eco) — https://github.com/pallets-eco/flask-pydantic — Pydantic v2 compatibility via PR #92 and PR #105; not directly run
- Flask best practices 2025 (DEV Community) — https://dev.to/gajanan0707/how-to-structure-a-large-flask-application-best-practices-for-2025-9j2 — structural recommendations
- API Pagination strategies 2025 — offset vs cursor justification at DockSentinel's scale
- SQLAlchemy repository pattern discussion — https://github.com/sqlalchemy/sqlalchemy/discussions/11354

### Tertiary (LOW confidence)
- Why Over-Abstraction Can Kill Your Codebase (Medium) — supports project-stated "no premature ABCs" principle; community source only

---
*Research completed: 2026-04-04*
*Ready for roadmap: yes*
