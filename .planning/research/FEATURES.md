# Feature Landscape: Flask/SQLAlchemy Refactor

**Domain:** Python Flask AIOps service (~3,300 LOC), refactor-only milestone
**Researched:** 2026-04-04
**Confidence:** HIGH — grounded in direct codebase inspection + verified against official Flask/SQLAlchemy/Alembic docs

---

## Table Stakes

Features users expect. Missing = product feels incomplete for a maintainable codebase.
For a refactor, "user" means the next developer (or future self) working on this code.

| Outcome | Why Expected | Complexity | Evidence From Codebase |
|---------|--------------|------------|------------------------|
| Eliminate duplicated `_call_llm` / `_settings` / `_prompt` methods | Three classes (`SentinelService`, `BriefingService`, `api/settings.py`) contain nearly identical LLM invocation code. Any bug fix must be applied in three places. | Low | `sentinel.py:92–122`, `briefing.py:25–56`, `settings.py:63–98` are ~95% identical |
| Replace `app.extensions["services"]` dict with typed container | String-keyed dict means typos fail at runtime, not import time. No IDE autocomplete, no refactor safety. | Low | `create_app()` line 317–325, consumed by string key in every route handler and API endpoint |
| Move web routes out of `create_app()` into a blueprint | 150+ LOC of route handlers inside the app factory makes the factory untestable in isolation and violates single responsibility. The API routes are already in blueprints — the web routes are the exception. | Low | `app/__init__.py` lines 121–286: `_register_web_routes` defines 9 route handlers inside a nested function |
| Replace hardcoded `ALTER TABLE` SQL in app factory with Alembic | 8 raw `ALTER TABLE` statements in `_ensure_settings_schema_compat()` are unversioned, not reversible, and brittle (SQLite limitations). New columns added to `Settings` require manually tracking which instances have been migrated. | Medium | `app/__init__.py` lines 77–98; the function is called on every app startup |
| Break `Settings` god object into domain-specific config classes | 25+ unrelated fields (LLM config, CLI config, Telegram config, scheduling config, call-reduction config) in one model. Adding a new notification channel means adding more fields to an already-crowded table. | Medium | `app/models/settings.py` lines 11–49 |
| Repository pattern for `AnalysisEvent` DB queries | `SentinelService.process_chunk()` and `_send_alert_if_allowed()` contain 5 inline `AnalysisEvent.query.filter(...)` calls. Same pattern repeated in `_register_web_routes`. Direct ORM queries in service logic couple business logic to SQLAlchemy API. | Medium | `sentinel.py:212–247`, `sentinel.py:305–329`, `__init__.py:128–148` |
| Increase test coverage to ~80%+ with integration tests | Current suite: 31 tests, ~40–50% coverage, no full pipeline integration tests. The core `process_chunk` pipeline (prefilter → dedup → rate limit → LLM → alert) is only partially covered. | Medium | `tests/test_sentinel_pipeline.py` is 211 LOC covering parts of the pipeline; no end-to-end test |
| Fix Docker setup (non-root user, health check, build cache) | Running as root in a container is a security baseline violation. Missing health check means Docker cannot detect a hung process. These are expected for any production-grade containerised service. | Low | Confirmed missing from `PROJECT.md` context |

---

## Differentiators

Outcomes that significantly improve developer experience beyond the baseline but are not blocking.

| Outcome | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Pydantic v2 request/response schemas on list endpoints | Currently `GET /api/insights` and `GET /api/events` return raw SQLAlchemy model dicts with no contract. Adding Pydantic response models makes the API self-documenting and catches serialisation regressions at test time. Pydantic v2 is already in the stack (`VerdictParser`). | Low–Medium | Only list/paginated endpoints need schemas; simple GET/singleton endpoints do not benefit enough to justify the work |
| API pagination on `GET /api/insights` (currently hard-limited to 200) | The `insights_page` view hard-limits to 200 rows. When the React SPA arrives (ROADMAP Phase 1), it will need cursor- or offset-based pagination. Adding it now avoids a breaking API change later. | Low | One endpoint (`api/insights.py`); the web route (`__init__.py:204`) independently hard-limits at 200 |
| `SentinelService` decomposed into explicit pipeline stages | Current service mixes log buffering, LLM dispatch, chunk dedup, rate limiting, and alert dispatch in one class. Decomposing into composable stages (e.g., `DeduplicationStage`, `RateLimitStage`, `LLMDispatchStage`) makes each stage unit-testable in isolation. | High | High complexity because the stages share Settings state and the DB session — requires careful dependency threading. Do not decompose prematurely. |
| `AlertStrategy` abstraction (Telegram, future Slack/email) | `_send_alert_if_allowed()` in `SentinelService` hardcodes Telegram. ROADMAP Phase 3 adds SMTP. A thin strategy interface (`send(event)`) isolates the transport from the cooldown/rate-limit logic, which is transport-agnostic. | Low–Medium | The cooldown and rate-limit logic stays in `SentinelService`; only the `telegram_notifier.send_message(...)` call moves behind the interface |
| Shared pytest fixtures and `conftest.py` structure | All 10 test files create their own app/client fixtures. Extracting shared fixtures to `tests/conftest.py` removes ~120 LOC of duplication and ensures consistent app configuration across the test suite. | Low | Purely additive; does not change test behaviour |
| Coverage measurement in CI (`pytest --cov`) | Currently there is no coverage gate. Adding `pytest-cov` with a minimum threshold (e.g., 75%) prevents coverage regression after the refactor without requiring a specific number upfront. | Low | Config change + `pyproject.toml` / `setup.cfg` entry |

---

## Anti-Features

Things to deliberately NOT do in this refactor.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Migrate `Settings` to multiple DB tables | Splitting one table into four (`llm_settings`, `alert_settings`, etc.) requires a schema migration, data migration, and updates to every query that references `Settings.singleton()`. The value is marginal for a single-user self-hosted tool. | Split into Python dataclasses / Pydantic config objects that are constructed from the single `Settings` ORM row. The DB schema stays flat; the code gets domain grouping. |
| Introduce abstract base classes (`AbstractRepository`, `AbstractAlertStrategy`) for 2 concrete implementations | Two concrete implementations do not justify an ABC. ABCs add indirection without enabling meaningful substitution at this scale. | Use plain Python protocols (structural typing) if type-checking is needed. Or just use the concrete class and add the interface when a second implementation actually exists. |
| Extract every shared helper into a utility module | "Three similar lines > one premature helper" (project standard). The `_settings()` / `_prompt()` duplication is real and should be fixed by injecting a shared service, not by adding a `utils.py` with loose functions. | Eliminate duplication via `LLMCallService` injection, not via a utility module. |
| Full pytest fixture mocking of SQLAlchemy sessions | Mocking the ORM session (with `MagicMock`) produces tests that pass while the real query logic is untested. The project standard is "integration tests hit real databases (Testcontainers)." | Use an in-memory SQLite test database (already in the existing fixture pattern) for service-layer integration tests. |
| Migrate from SQLite to PostgreSQL | Out of scope per `PROJECT.md`. SQLite is adequate for a single-host, self-hosted AIOps agent. Migration adds complexity with zero user-visible benefit at current scale. | Keep SQLite. Alembic with `render_as_batch=True` handles SQLite's ALTER TABLE limitations. |
| Event sourcing / domain events for pipeline stages | The pipeline is a synchronous, single-process loop. Event-sourcing the stages adds a message broker dependency and async complexity that is not justified by the problem. | Keep the pipeline synchronous. Decompose into method calls, not events. |
| FastAPI migration | Working framework, Flask stays per explicit constraint in `PROJECT.md`. FastAPI would change the async model and break all existing tests. | Stay on Flask. Add Pydantic v2 schemas within Flask using `request.get_json()` + manual validation. |
| GraphQL API layer | Overkill for a self-hosted tool with fewer than 10 API endpoints. The React SPA planned in ROADMAP Phase 1 is well-served by the existing REST endpoints. | Keep REST. Add pagination and Pydantic response models on the handful of list endpoints. |

---

## Feature Dependencies

Dependency graph for the table stakes and differentiators:

```
Alembic migrations
  └── Settings god object decomposition
        (safe to decompose in code once Alembic owns schema evolution)

Typed service container
  └── Repository pattern
        (repositories injected via container, not fetched via ORM in service methods)

Eliminate duplicated _call_llm
  └── LLMCallService (single class, injected)
        ├── SentinelService refactor
        └── BriefingService refactor
              └── AlertStrategy abstraction
                    (AlertStrategy depends on SentinelService having a clean boundary)

Web routes blueprint
  └── No hard dependencies, but enables:
        └── Isolated factory tests

Shared fixtures / conftest.py
  └── Integration tests (prerequisite: fixtures must be reliable before adding more tests)
        └── Coverage gate in CI
```

**Ordering implication:** Alembic must be introduced before any Settings decomposition that touches the DB schema. `LLMCallService` extraction is the highest-leverage single change (removes ~120 LOC of duplication, no schema impact, low blast radius). Repository pattern follows the typed container because repositories are injected, not ad-hoc fetched.

---

## MVP Recommendation for This Refactor Milestone

Prioritize in this order (each independently shippable per project constraint):

1. **`LLMCallService` extraction** — eliminates the most concrete duplication, lowest blast radius, no schema changes. Immediate win.
2. **Typed service container** — replaces `app.extensions["services"]` dict. Low complexity, enables everything downstream.
3. **Web routes blueprint** — moves 150 LOC out of the factory. Independent from the service refactor.
4. **Alembic setup + Settings decomposition** — medium complexity, foundational for future schema changes. Do Alembic first, then decompose Settings in code.
5. **Repository pattern** — follows the typed container. Required before test coverage can meaningfully improve for service logic.
6. **Integration tests + coverage gate** — final phase, after structure stabilises.
7. **Docker hardening** — independent, low complexity, fits alongside any phase.

Defer to phase-specific research:
- `SentinelService` pipeline decomposition: High complexity. Flag for a dedicated research spike before implementation. The interaction between `LogBuffer` state, DB session, and `Settings` singleton needs careful mapping before decomposing.
- `AlertStrategy` abstraction: Implement after `LLMCallService` extraction, because the clean boundary becomes obvious once the LLM service is extracted.

---

## Sources

- [Architecture Patterns with Python — Repository Pattern](https://www.cosmicpython.com/book/chapter_02_repository.html) — O'Reilly, Percival & Gregory (HIGH confidence, book-level authority)
- [Flask-Migrate documentation](https://flask-migrate.readthedocs.io/) — Official docs (HIGH confidence)
- [Alembic autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — Official docs (HIGH confidence)
- [Alembic batch mode for SQLite](https://alembic.sqlalchemy.org/en/latest/batch.html) — Official docs (HIGH confidence); confirms `render_as_batch=True` is the correct approach for SQLite ALTER TABLE
- [Flask Blueprint — Real Python](https://realpython.com/flask-blueprint/) — MEDIUM confidence (community, well-maintained)
- [Refactoring a Flask App with Blueprints — Atomic Object](https://spin.atomicobject.com/refactoring-flask-blueprints/) — MEDIUM confidence (community case study)
- [Why Over-Abstraction Can Kill Your Codebase — Medium](https://medium.com/@vbansal0803/why-over-abstraction-can-kill-your-code-base-1e6911771a56) — LOW confidence (community), supports project-stated principle
