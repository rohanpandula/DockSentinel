# Architecture Patterns: Flask/SQLAlchemy Layered Refactor

**Domain:** AIOps observability agent (Flask/SQLAlchemy monolith refactor)
**Researched:** 2026-04-04
**Confidence:** HIGH — patterns sourced from Architecture Patterns with Python (cosmic python), Flask documentation, and direct codebase analysis.

---

## Recommended Architecture

The target is a four-layer architecture where each layer only communicates with the layer directly below it. No layer skips a level. The current codebase violates this at every boundary — routes write to the DB directly, services hold raw queries, and the app factory owns both wiring and web routes.

```
┌─────────────────────────────────────────────────────┐
│  Presentation Layer                                 │
│  Flask Blueprints (web routes + API routes)         │
│  Pydantic request/response schemas                  │
│  No business logic, no raw SQL                      │
└──────────────────────┬──────────────────────────────┘
                       │ calls
┌──────────────────────▼──────────────────────────────┐
│  Service Layer                                      │
│  SentinelPipeline, BriefingService, LLMCallService  │
│  AlertService (strategy-dispatched)                 │
│  Orchestrates domain objects, never touches DB      │
└──────────────────────┬──────────────────────────────┘
                       │ calls
┌──────────────────────▼──────────────────────────────┐
│  Repository Layer                                   │
│  AnalysisEventRepository, SettingsRepository        │
│  PromptRepository, ReportRepository                 │
│  ExclusionRepository                                │
│  All raw SQLAlchemy queries live here               │
└──────────────────────┬──────────────────────────────┘
                       │ calls
┌──────────────────────▼──────────────────────────────┐
│  Infrastructure / Models                            │
│  SQLAlchemy ORM models (unchanged)                  │
│  Alembic migration files                            │
│  extensions.py (db singleton)                       │
└─────────────────────────────────────────────────────┘
```

---

## Component Boundaries

### What Each Component Owns

| Component | Owns | Does NOT Touch |
|-----------|------|----------------|
| Flask Blueprints | HTTP request parsing, response serialisation, redirects | DB sessions, service internals, config fields |
| Service Layer | Business rules (dedup, rate limiting, call reduction) | HTTP context, raw SQL, `db.session` |
| Repository Layer | All SQLAlchemy queries, `db.session` | Business rules, service state |
| LLMCallService | LLM invocation, transport selection, timeout/retry resolution | Prompt text, routing logic, alert sending |
| AlertService | Channel dispatch (Telegram now, Slack/email later) | Classification logic, rate limit queries |
| Config dataclasses | Setting field grouping for a single domain | Cross-domain settings, service state |
| ServiceContainer | Wiring services together, lifetime management | Business logic, HTTP |
| RuntimeCoordinator | Process lifecycle, scheduler, watcher | Service internals, route handlers |

### Component Responsibilities in Detail

**LLMCallService** (new, extracted from sentinel.py + briefing.py + api/settings.py)

The `_call_llm` method is duplicated across three files with ~40 LOC of identical transport-dispatch logic. Extract once:

```python
class LLMCallService:
    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    def call(
        self,
        *,
        config: LLMConfig,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LLMResult:
        # resolves transport, timeout, retries from config
        # delegates to llm_client.complete()
```

`SentinelPipeline`, `BriefingService`, and the test-LLM endpoint all call this single method. No service ever calls `llm_client` directly.

**SentinelPipeline** (refactored from monolithic SentinelService)

The current `SentinelService.process_chunk` (lines 189–303 of sentinel.py) mixes five responsibilities. The refactored version is a pipeline where each stage is a pure method that takes a value and returns a value or an `AnalysisEvent` with a terminal status:

```
handle_log_line()
  → prefilter stage (PreFilter.match)
  → buffer stage (LogBuffer.add_line)
  → [for each chunk] process_chunk()
      → keyword check stage       → status="skipped" if no match
      → dedup stage               → status="dedup_skipped" if hash seen
      → rate limit stage          → status="rate_limited" if over limit
      → LLM call stage            → status="llm_error" on failure
      → parse stage               → status="parse_error" on bad JSON
      → persist + alert stage     → status="analyzed", alert dispatched
```

Each stage reads from a repository — it never calls `db.session` directly.

**AlertService** (extracted from `_send_alert_if_allowed` in sentinel.py)

```python
class AlertStrategy(Protocol):
    def send(self, event: AnalysisEvent, settings: AlertConfig) -> tuple[bool, str | None]: ...

class TelegramAlertStrategy:
    def send(self, event: AnalysisEvent, settings: AlertConfig) -> tuple[bool, str | None]: ...

class AlertService:
    def __init__(self, strategies: list[AlertStrategy], event_repo: AnalysisEventRepository) -> None: ...
    def dispatch_if_allowed(self, event: AnalysisEvent, config: AlertConfig) -> tuple[bool, str | None]: ...
```

The cooldown check and global rate limit check stay inside `AlertService`. The channel (Telegram) is injected as a strategy. This is the minimal hook for ROADMAP Phase 3/5 without building multi-channel now.

**Repository Layer**

Each repository is a class that wraps `db.session`. No business logic. No service imports.

```python
class AnalysisEventRepository:
    def add(self, event: AnalysisEvent) -> None: ...
    def get(self, id: int) -> AnalysisEvent | None: ...
    def recent_by_hash(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None: ...
    def count_recent_by_container(self, container_id: str, since: datetime) -> int: ...
    def recent_alert_sent_count(self, since: datetime) -> int: ...
    def list_paginated(self, page: int, per_page: int, filters: EventFilters) -> Page[AnalysisEvent]: ...

class SettingsRepository:
    def singleton(self) -> Settings: ...
    def save(self, settings: Settings) -> None: ...

class PromptRepository:
    def get_by_key(self, key: PromptKey) -> PromptTemplate: ...
    def list_all(self) -> list[PromptTemplate]: ...
    def save(self, template: PromptTemplate) -> None: ...
```

Query methods currently scattered across `SentinelService.process_chunk`, `SentinelService._send_alert_if_allowed`, `BriefingService.generate_report`, and `__init__.py` route handlers all move here.

**Config Dataclasses** (split from Settings god object)

The `Settings` ORM model must retain all 25+ columns — the database schema does not change. The split happens at the read boundary: a factory converts one `Settings` row into domain-specific frozen dataclasses that services accept:

```python
@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    provider: str
    transport: str
    cli_backend: str
    timeout_seconds: int
    max_retries: int
    cli_timeout_seconds: int
    cli_max_retries: int

@dataclass(frozen=True)
class AlertConfig:
    cooldown_minutes: int
    rate_limit_count: int
    rate_limit_window_seconds: int
    telegram_token: str | None
    telegram_chat_id: str | None

@dataclass(frozen=True)
class CallReductionConfig:
    dedup_window_seconds: int
    container_rate_limit_count: int
    container_rate_limit_window_seconds: int
    keyword_flush_delay_lines: int

@dataclass(frozen=True)
class BufferConfig:
    max_input_chars: int
    max_input_tokens: int
    reserved_output_tokens: int
    token_estimation_strategy: str
    keyword_list: str
```

Services accept `LLMConfig`, `AlertConfig`, etc. as arguments — never the raw `Settings` object. The `SettingsRepository.singleton()` returns a `Settings` ORM row; a `SettingsService` (or factory function) converts it to the right config dataclass on demand.

**ServiceContainer** (replaces `app.extensions["services"]` dict)

```python
@dataclass
class ServiceContainer:
    llm_client: LLMClient
    cli_runner: CLIBackendRunner
    verdict_parser: VerdictParser
    llm_call_service: LLMCallService
    sentinel_pipeline: SentinelPipeline
    briefing_service: BriefingService
    alert_service: AlertService
    coordinator: RuntimeCoordinator
```

`create_app()` builds one `ServiceContainer`, stores it as `app.extensions["services"]`. Route handlers access it as `container = current_app.extensions["services"]` with a typed helper:

```python
def get_services() -> ServiceContainer:
    return current_app.extensions["services"]  # type: ignore[return-value]
```

Existing tests that do `app.extensions["services"]["sentinel"]` need a one-line migration to `app.extensions["services"].sentinel_pipeline`. This is a small test-only change, not a behavioral one.

**Web Blueprint** (extracted from app factory)

All `_register_web_routes` inline functions move to `app/web/routes.py` as a proper Blueprint. The route functions themselves stay nearly identical — the only change is that they call `get_services()` and repository methods instead of raw model queries and the `app.extensions` dict directly.

**Alembic** (replaces `_ensure_settings_schema_compat`)

The eight `ALTER TABLE` statements in `_ensure_settings_schema_compat` become Alembic migrations. The function is deleted from `create_app()`. `db.create_all()` remains in place for the test in-memory case but is gated to `TESTING=true` to avoid overriding Alembic in production.

---

## Data Flow

### Real-Time Log Analysis (hot path)

```
Docker event
  → DockerWatcher._event_thread
  → line_callback(container_id, container_name, line, flush_only=False)
  → SentinelPipeline.handle_log_line()
      reads: ExclusionRepository.is_excluded(container_name)
      reads: SettingsRepository.singleton() → BufferConfig
      → LogBuffer.add_line() [in-memory]
      [on chunk ready]
      → SentinelPipeline.process_chunk()
          reads: SettingsRepository.singleton() → CallReductionConfig
          reads: AnalysisEventRepository.recent_by_hash()       [dedup check]
          reads: AnalysisEventRepository.count_recent_by_container() [rate limit]
          reads: PromptRepository.get_by_key()
          calls: LLMCallService.call()
          calls: VerdictParser.safe_parse()
          writes: AnalysisEventRepository.add(event)
          calls: AlertService.dispatch_if_allowed()
              reads: AnalysisEventRepository.recent_alert_sent_count()
              calls: TelegramAlertStrategy.send()
```

### Nightly Briefing (scheduled path)

```
APScheduler cron trigger
  → RuntimeCoordinator._run_nightly_job()
  → BriefingService.generate_report()
      reads: SettingsRepository.singleton() → LLMConfig
      reads: PromptRepository.get_by_key() [NIGHTLY_SYSTEM, NIGHTLY_REPORT]
      reads: AnalysisEventRepository.list_for_window(period_start, period_end)
      calls: LLMCallService.call()
      writes: ReportRepository.add(report)
```

### Settings Update (write path)

```
HTTP PUT /api/settings
  → settings_api Blueprint
  → Pydantic SettingsUpdateRequest.model_validate(request.json)
  → SettingsRepository.singleton() → mutate fields → SettingsRepository.save()
  → coordinator.refresh_schedule()
  → return SettingsResponse.model_validate(settings.as_dict())
```

---

## Incremental Refactor Order

This is the build order that respects dependencies and keeps tests green at each step.

### Phase A: Foundation (no behavior change, lowest risk)

1. **Extract `LLMCallService`** — the most mechanical change. Three files become one. Update `SentinelService`, `BriefingService`, `api/settings.py` to call `LLMCallService.call()`. All three sets of tests pass with the same DummyLLM doubles.

2. **Add `ServiceContainer` dataclass** — replace `app.extensions["services"]` dict. The dict key names become typed attributes. Update `create_app()` to assign a `ServiceContainer` instance. Update all route handlers and tests to use attribute access. Zero behavior change.

3. **Add config dataclasses** — create `LLMConfig`, `AlertConfig`, `CallReductionConfig`, `BufferConfig`. `Settings.singleton()` stays; add a `Settings.to_llm_config()` factory method (or standalone `build_llm_config(settings)` function). Update services to accept config objects as arguments. Zero behavior change — services still call `SettingsRepository` to get the latest row.

**Dependency:** Phase A items are independent of each other and can be done in parallel PRs. None touches the DB or test fixtures.

### Phase B: Repository Layer (touches DB access)

4. **Create repositories** — `AnalysisEventRepository`, `SettingsRepository`, `PromptRepository`, `ReportRepository`, `ExclusionRepository`. Each wraps existing query patterns with named methods. The services continue to call `db.session` in parallel during transition — this is a copy-then-delete approach, not a cut-over.

5. **Wire repositories into SentinelPipeline** — replace raw `db.session` and `Model.query` calls in `sentinel.py` with repository method calls. Run the 31 tests. Green = proceed.

6. **Wire repositories into BriefingService, api/*.py, web routes** — same pattern. Each file is a separate PR.

**Dependency:** Repositories must exist (step 4) before services are wired to them (steps 5–6).

### Phase C: Alembic (migration infrastructure)

7. **Bootstrap Alembic** — `flask db init`, create initial migration from current schema state. Gate `db.create_all()` to `TESTING=true`. Verify `flask db upgrade` produces the same schema as `db.create_all()`.

8. **Convert `_ensure_settings_schema_compat` to migrations** — write one Alembic migration per column add. Delete `_ensure_settings_schema_compat` from `create_app()`. Test by running upgrade on a DB that has the old schema.

**Dependency:** Must come after repositories exist so the migration test path is clean. Can be done in parallel with Phase B steps 5–6.

### Phase D: Service decomposition (highest complexity)

9. **Extract `AlertService`** — move `_send_alert_if_allowed` out of `SentinelPipeline`. Create `TelegramAlertStrategy` wrapping `TelegramNotifier`. Wire `AlertService` into `ServiceContainer`. Update pipeline to call `alert_service.dispatch_if_allowed()`.

10. **Extract web Blueprint** — move `_register_web_routes` inline functions to `app/web/routes.py` as a Blueprint. Register it via `_register_web_routes(app)` that now just calls `app.register_blueprint(web_bp)`. Zero behavior change — route function bodies are identical.

11. **Split Settings god object (display only)** — the `Settings` ORM model keeps all columns. The config dataclass factories now return frozen objects. Services use these frozen objects. The settings form POST in the web Blueprint still mutates the ORM row directly (same as today).

**Dependency:** AlertService extraction (9) requires `AnalysisEventRepository` to exist. Web Blueprint extraction (10) is independent.

### Phase E: Pydantic validation + pagination

12. **Add Pydantic schemas for API endpoints** — `SettingsUpdateRequest`, `SettingsResponse`, `EventListResponse`, `PagedResponse[T]`. Apply to `api/settings.py`, `api/insights.py`, `api/reports.py` first (highest traffic). Web routes keep form handling as-is.

13. **Pagination on list endpoints** — `AnalysisEventRepository.list_paginated()` method. Apply to `GET /api/insights` and `GET /api/reports`. Web route `insights_page` gets a `page` query param added.

**Dependency:** Repository layer must exist for paginated query methods.

---

## Anti-Patterns to Avoid

### 1. Service Layer Calling `db.session` Directly

**What it looks like:** `SentinelPipeline.process_chunk` calling `db.session.add(event)` and `db.session.commit()`.

**Why bad:** Services become untestable without a real DB. The current test suite works around this by building a real SQLite DB for every test — that's Testcontainers-style and acceptable for integration tests, but unit tests of pipeline logic should not need a DB at all.

**Instead:** Services call `AnalysisEventRepository.add(event)`. The repository calls `db.session.add()` and `db.session.commit()`. In unit tests, inject a `FakeAnalysisEventRepository` that stores events in a list.

### 2. Repositories Containing Business Logic

**What it looks like:** `AnalysisEventRepository.add_if_not_rate_limited()` or `ExclusionRepository.record_if_not_recent()`.

**Why bad:** Business rules that change frequently (rate limit counts, cooldown windows) end up buried in query objects. Testing them requires DB fixtures.

**Instead:** Rate limit logic lives in `SentinelPipeline`. The repository only provides a count: `count_recent_by_container(container_id, since)`. The pipeline decides what to do with that count.

### 3. Cutting Over All at Once

**What it looks like:** A single PR that replaces `SentinelService` with `SentinelPipeline`, adds repositories, adds config dataclasses, and adds Alembic all at once.

**Why bad:** When tests break (they will), the cause is invisible.

**Instead:** Follow the Phase A → B → C → D → E order. Each step is a green PR. `LLMCallService` extraction (step 1) touches the fewest files and is the best smoke-test of the overall approach.

### 4. God Container Leaking into Domain Code

**What it looks like:** A service file importing `ServiceContainer` to resolve its own dependencies.

**Why bad:** Creates circular imports and couples service internals to the wiring layer.

**Instead:** All services receive their dependencies via `__init__` constructor arguments. Only `create_app()` touches `ServiceContainer`. Route handlers access the container via `get_services()` and pass specific service instances to service methods as needed.

### 5. Alembic + `db.create_all()` Coexisting in Production

**What it looks like:** `create_app()` calling `db.create_all()` unconditionally.

**Why bad:** `db.create_all()` does not run migrations — it creates missing tables at their current schema, silently bypassing pending migrations.

**Instead:** `db.create_all()` is gated to `app.config["TESTING"] == True`. Production startup runs `alembic upgrade head` as a Docker entrypoint step before starting Gunicorn.

---

## Directory Structure After Refactor

```
app/
  __init__.py           # create_app() — wiring only, ~80 LOC
  config.py             # AppConfig (env vars) — unchanged
  extensions.py         # db singleton — unchanged
  time_utils.py         # unchanged

  models/               # ORM models — unchanged (schema untouched)
    settings.py
    events.py
    ...

  repositories/         # NEW — all SQLAlchemy queries
    analysis_events.py
    settings.py
    prompts.py
    reports.py
    exclusions.py

  config_objects/       # NEW — domain config dataclasses
    llm.py              # LLMConfig
    alert.py            # AlertConfig
    call_reduction.py   # CallReductionConfig
    buffer.py           # BufferConfig

  services/
    llm_call.py         # NEW — LLMCallService (extracted from 3 files)
    alert.py            # NEW — AlertService + AlertStrategy Protocol
    sentinel.py         # REFACTORED — SentinelPipeline
    briefing.py         # REFACTORED — uses LLMCallService
    coordinator.py      # REFACTORED — uses ServiceContainer
    # unchanged:
    llm_client.py
    cli_backends.py
    log_buffer.py
    prefilter.py
    verdict_parser.py
    telegram.py
    docker_watcher.py

  api/                  # API blueprints — add Pydantic schemas
    settings.py
    exclusions.py
    insights.py
    reports.py
    sentinel.py
    prompts.py
    health.py
    telegram.py

  web/                  # NEW — extracted from app factory
    routes.py           # all Jinja2 web routes as a Blueprint

  container.py          # NEW — ServiceContainer dataclass

migrations/             # NEW — Alembic migration files
alembic.ini             # NEW
```

---

## Scalability Considerations

This is a single-process Docker service. The architecture decisions that matter for this scale:

| Concern | Current state | After refactor |
|---------|--------------|----------------|
| DB queries per log chunk | 6–8 inline `db.session` calls scattered across `process_chunk` | Same 6–8 calls, but isolated in repositories — easier to add query caching or batching later |
| Schema migration | 8 hardcoded `ALTER TABLE` statements, run on every startup | Alembic tracks applied migrations — startup only runs pending ones |
| Test DB isolation | Each test creates a new SQLite file via `tmp_path` | Same — repositories make it easier to inject a fake for pure-logic unit tests |
| Adding alert channels | Requires forking `_send_alert_if_allowed` | Add a new `AlertStrategy` implementation, register in `ServiceContainer` |
| LLM transport changes | Requires modifying 3 files | Modify `LLMCallService.call()` only |

---

## Sources

- [Architecture Patterns with Python — Service Layer](https://www.cosmicpython.com/book/chapter_04_service_layer.html) — HIGH confidence
- [Architecture Patterns with Python — Repository Pattern](https://www.cosmicpython.com/book/chapter_02_repository.html) — HIGH confidence
- [Architecture Patterns with Python — Dependency Injection](https://www.cosmicpython.com/book/chapter_13_dependency_injection.html) — HIGH confidence
- [Flask-Migrate documentation](https://flask-migrate.readthedocs.io/) — HIGH confidence
- [Alembic autogenerate documentation](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) — HIGH confidence
- [Flask Patterns documentation](https://flask.palletsprojects.com/en/stable/patterns/) — HIGH confidence
- [Refactoring.Guru — Strategy Pattern in Python](https://refactoring.guru/design-patterns/strategy/python/example) — HIGH confidence
