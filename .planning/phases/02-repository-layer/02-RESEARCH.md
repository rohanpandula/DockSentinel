# Phase 2: Repository Layer - Research

**Researched:** 2026-04-04
**Domain:** SQLAlchemy repository pattern, Flask-SQLAlchemy session management, Python class extraction
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Session & Transaction Ownership**
- D-01: Repositories never call `db.session.commit()`. The caller (service or route handler) owns the commit — this preserves atomicity for multi-step flows like sentinel's dedup-check → LLM-call → save-event → alert-check pipeline.
- D-02: Repositories import `db` from `app.extensions` (not constructor-injected). This matches the existing codebase pattern used in all model and service files, and Flask-SQLAlchemy's request-scoped session handling makes this safe.

**Repository Injection & Wiring**
- D-03: Repositories are added as typed attributes on the existing `ServiceContainer` dataclass from Phase 1 (`container.event_repo`, `container.settings_repo`, `container.prompt_repo`, `container.report_repo`, `container.exclusion_repo`).
- D-04: Services receive repositories via constructor injection — e.g., `SentinelService.__init__(event_repo, prompt_repo, ...)`. This extends the Phase 1 pattern where services already accept `llm_client`, `verdict_parser`, etc. as constructor args.
- D-05: Route handlers access repositories through the container (same as services): `container.event_repo.get_recent(limit=10)`.

**Singleton Model Handling**
- D-06: `SettingsRepository` is created to wrap `Settings.singleton()` and the update/commit pattern used in `api/settings.py`. Required by REPO-02.
- D-07: `SentinelState` and `SchemaVersion` keep their existing `singleton()` classmethods — they are internal infrastructure with 1-2 call sites each. No repository needed.

**Query Method Granularity**
- D-08: Each repository has domain-named methods matching current inline queries: `count_recent_calls(minutes)`, `find_duplicate_chunk(hash, hours)`, `get_recent_alerts(hours)`, etc. No generic base class with `get_by_id` / `find_all`.
- D-09: Repositories return ORM model instances, not dicts. `as_dict()` serialization stays on the model classes — it's a presentation concern. Phase 5 will replace `as_dict()` with Pydantic response models.

### Claude's Discretion
- Exact method signatures and parameter naming on each repository class
- Internal helper methods within repositories (e.g., shared date-range filtering)
- Order of migration (which repo to extract first)
- Whether to extract `app/__init__.py` web route queries in this phase or defer to Phase 4 (Blueprint extraction) — both are valid since REPO-03 says "no inline queries in services and routes"

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPO-01 | AnalysisEventRepository encapsulates all AnalysisEvent ORM queries currently scattered across services and routes | 15 inline query/session call sites confirmed across sentinel.py, briefing.py, and app/__init__.py web routes. All map to discrete repository methods. |
| REPO-02 | SettingsRepository, PromptRepository, ReportRepository, ExclusionRepository created for remaining models | Each model's query sites catalogued: prompts.py (5 calls), reports.py (2 calls), exclusions.py (6 calls), settings.py (1 commit call). All wrap straightforward CRUD or key-based lookups. |
| REPO-03 | No service or route handler contains inline SQLAlchemy query calls after repository migration | Covers app/services/*.py and app/api/*.py; `app/__init__.py` web routes are also in scope per CONTEXT.md. |
</phase_requirements>

---

## Summary

Phase 2 extracts all inline SQLAlchemy ORM query calls from service and route handler code into five named repository classes under `app/repositories/`. The current codebase has approximately 52 inline call sites spread across `sentinel.py` (~20 calls), `briefing.py` (3 calls), `api/prompts.py` (5 calls), `api/reports.py` (2 calls), `api/exclusions.py` (6 calls), `api/settings.py` (1 call), `app/__init__.py` web routes (~15 calls), and `services/coordinator.py` (1 call). All five model types (`AnalysisEvent`, `Settings`, `PromptTemplate`, `DailyReport`, `ExclusionRule`) map to exactly one repository each.

The key infrastructure already exists from Phase 1: `ServiceContainer` is a typed `@dataclass`, `app/extensions.py` exposes the `db` singleton, and services already accept dependencies via constructor injection. This phase extends those patterns. There are no new dependencies to add — the work is purely extracting existing query code into encapsulated classes and wiring them into the container.

The riskiest aspect of this phase is the `AnalysisEventRepository`, which encapsulates the most complex queries (dedup window, per-container rate limit, alert cooldown, and alert rate limit). All four query shapes involve `and_()` multi-condition filters with `timedelta`-based date windows — these must be migrated without altering their logic since 7 of the 31 existing tests exercise these code paths directly.

**Primary recommendation:** Extract repositories in dependency order — `AnalysisEventRepository` first (highest usage, most risk), then `PromptRepository` (both services depend on it), then `ExclusionRepository`, `ReportRepository`, and `SettingsRepository` last (one call site each in services). Wire each into `ServiceContainer` and update one call site file per task, verifying all 31 tests pass after each wiring step.

---

## Standard Stack

### Core (already installed — no additions required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-SQLAlchemy | 3.1.1 | Provides `db` scoped session, `db.Model` base, `db.session` | Already in stack; scoped session per request is the correct session management model for Flask |
| SQLAlchemy | 2.0.36 | ORM core — query API, `and_()`, `.filter()`, `.count()`, `db.session.get()` | Already in stack |

### No New Libraries Required

This phase adds zero new runtime dependencies. The repository classes are pure Python using the existing SQLAlchemy session. No new packages to install.

---

## Architecture Patterns

### Recommended Project Structure (after this phase)

```
app/
├── repositories/              # NEW in this phase
│   ├── __init__.py            # empty
│   ├── analysis_events.py     # AnalysisEventRepository
│   ├── exclusions.py          # ExclusionRepository
│   ├── prompts.py             # PromptRepository
│   ├── reports.py             # ReportRepository
│   └── settings.py            # SettingsRepository
├── services/
│   ├── sentinel.py            # UPDATED — receives repos as constructor args
│   ├── briefing.py            # UPDATED — receives repos as constructor args
│   └── coordinator.py         # UPDATED — removes its db.session.commit() call
├── api/
│   ├── exclusions.py          # UPDATED — uses container.exclusion_repo
│   ├── prompts.py             # UPDATED — uses container.prompt_repo
│   ├── reports.py             # UPDATED — uses container.report_repo
│   └── settings.py            # UPDATED — uses container.settings_repo
├── container.py               # UPDATED — adds 5 repo attributes
└── __init__.py                # UPDATED — instantiates repos in create_app()
```

### Pattern 1: Domain-Named Repository Class

**What:** A plain class that imports `db` from `app.extensions`, contains query methods named after the domain operation, and never contains business logic.

**When to use:** Every ORM model that has more than one call site gets a repository. Methods are named for what they do in domain terms, not SQL terms.

**Example (AnalysisEventRepository skeleton):**

```python
# app/repositories/analysis_events.py
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_

from app.extensions import db
from app.models.events import AnalysisEvent


class AnalysisEventRepository:
    """Encapsulates all SQLAlchemy queries for AnalysisEvent."""

    def add(self, event: AnalysisEvent) -> None:
        """Add event to session. Caller commits."""
        db.session.add(event)

    def get(self, event_id: int) -> AnalysisEvent | None:
        return db.session.get(AnalysisEvent, event_id)

    def find_duplicate_chunk(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None:
        """Return the first non-skipped event with this hash after `since`."""
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.chunk_hash == chunk_hash,
                AnalysisEvent.status.notin_(["skipped"]),
                AnalysisEvent.created_at >= since,
            )
        ).first()

    def count_recent_by_container(self, container_id: str, since: datetime) -> int:
        """Count analyzed/error events for this container after `since`."""
        return AnalysisEvent.query.filter(
            and_(
                AnalysisEvent.container_id == container_id,
                AnalysisEvent.status.in_(["analyzed", "parse_error", "llm_error"]),
                AnalysisEvent.created_at >= since,
            )
        ).count()

    def find_alert_duplicate(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None:
        """Return an event with this hash where alert was already sent after `since`."""
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.chunk_hash == chunk_hash,
                    AnalysisEvent.alert_sent.is_(True),
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def count_recent_alerts(self, since: datetime) -> int:
        """Count events where alert_sent=True after `since`."""
        return AnalysisEvent.query.filter(
            and_(AnalysisEvent.alert_sent.is_(True), AnalysisEvent.created_at >= since)
        ).count()

    def find_recent_excluded(self, container_id: str, since: datetime) -> AnalysisEvent | None:
        """Return the most recent excluded event for this container after `since`."""
        return (
            AnalysisEvent.query.filter(
                and_(
                    AnalysisEvent.container_id == container_id,
                    AnalysisEvent.status == "excluded",
                    AnalysisEvent.created_at >= since,
                )
            )
            .order_by(AnalysisEvent.created_at.desc())
            .first()
        )

    def get_for_window(self, since: datetime) -> list[AnalysisEvent]:
        """Return all events created after `since`, ordered ascending."""
        return (
            AnalysisEvent.query.filter(AnalysisEvent.created_at >= since)
            .order_by(AnalysisEvent.created_at.asc())
            .all()
        )

    def get_recent(self, limit: int) -> list[AnalysisEvent]:
        """Return the N most recent events, descending."""
        return AnalysisEvent.query.order_by(AnalysisEvent.created_at.desc()).limit(limit).all()

    def get_today(self, today_start: datetime) -> list[AnalysisEvent]:
        """Return all events since midnight today."""
        return AnalysisEvent.query.filter(AnalysisEvent.created_at >= today_start).all()

    def get_filtered(
        self,
        container: str | None = None,
        classification: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 200,
    ) -> list[AnalysisEvent]:
        """Return filtered events for the insights page."""
        query = AnalysisEvent.query
        if container:
            query = query.filter(AnalysisEvent.container_name == container)
        if classification:
            query = query.filter(AnalysisEvent.classification == classification)
        if start:
            query = query.filter(AnalysisEvent.created_at >= start)
        if end:
            query = query.filter(AnalysisEvent.created_at <= end)
        return query.order_by(AnalysisEvent.created_at.desc()).limit(limit).all()

    def get_distinct_container_names(self) -> list[str]:
        """Return distinct non-null container names for the insights filter."""
        return [
            c[0]
            for c in db.session.query(AnalysisEvent.container_name).distinct().all()
            if c[0]
        ]
```

### Pattern 2: Settings Singleton Repository

**What:** `SettingsRepository` wraps `Settings.singleton()` and the session commit for settings updates. Services and routes call `settings_repo.get()` instead of `Settings.singleton()` directly.

**Example:**

```python
# app/repositories/settings.py
from __future__ import annotations

from app.extensions import db
from app.models.settings import Settings


class SettingsRepository:
    """Wraps the Settings singleton access and update commit."""

    def get(self) -> Settings:
        """Return the single Settings row, auto-creating if absent."""
        return Settings.singleton()

    def save(self) -> None:
        """Commit pending changes to the Settings row. Caller mutates fields."""
        db.session.commit()
```

Note: `save()` here simply commits — callers mutate the ORM instance directly then call `save()`. This matches the existing pattern in `api/settings.py` where fields are set via `setattr` before `db.session.commit()`. Do not add a `settings: Settings` parameter to `save()` — the ORM instance is already tracked by the session.

### Pattern 3: Simple CRUD Repository

**What:** Thin repositories for `PromptTemplate`, `DailyReport`, and `ExclusionRule` with 3-5 named methods. No complex filters.

**Example (PromptRepository):**

```python
# app/repositories/prompts.py
from __future__ import annotations

from app.extensions import db
from app.models.prompts import PromptKey, PromptTemplate


class PromptRepository:
    """Encapsulates all PromptTemplate ORM queries."""

    def get_by_key(self, key: PromptKey | str) -> PromptTemplate | None:
        key_value = key.value if isinstance(key, PromptKey) else key
        return PromptTemplate.query.filter_by(key=key_value).first()

    def list_all(self) -> list[PromptTemplate]:
        return PromptTemplate.query.order_by(PromptTemplate.key.asc()).all()
```

**Example (ExclusionRepository):**

```python
# app/repositories/exclusions.py
from __future__ import annotations

from app.extensions import db
from app.models.exclusions import ExclusionRule


class ExclusionRepository:
    """Encapsulates all ExclusionRule ORM queries."""

    def list_enabled(self) -> list[ExclusionRule]:
        return ExclusionRule.query.filter_by(enabled=True).all()

    def list_all(self) -> list[ExclusionRule]:
        return ExclusionRule.query.order_by(ExclusionRule.container_pattern.asc()).all()

    def find_by_pattern(self, pattern: str) -> ExclusionRule | None:
        return ExclusionRule.query.filter_by(container_pattern=pattern).first()

    def get(self, rule_id: int) -> ExclusionRule | None:
        return db.session.get(ExclusionRule, rule_id)

    def add(self, rule: ExclusionRule) -> None:
        db.session.add(rule)

    def delete(self, rule: ExclusionRule) -> None:
        db.session.delete(rule)
```

### Pattern 4: ServiceContainer Extension

**What:** Add repo attributes to the existing `ServiceContainer` dataclass and instantiate repos in `create_app()`.

**Container update:**

```python
# app/container.py (additions to existing dataclass)
from app.repositories.analysis_events import AnalysisEventRepository
from app.repositories.settings import SettingsRepository
from app.repositories.prompts import PromptRepository
from app.repositories.reports import ReportRepository
from app.repositories.exclusions import ExclusionRepository

@dataclass
class ServiceContainer:
    # ... existing attributes ...
    event_repo: AnalysisEventRepository
    settings_repo: SettingsRepository
    prompt_repo: PromptRepository
    report_repo: ReportRepository
    exclusion_repo: ExclusionRepository
```

**create_app() wiring:**

```python
# In create_app(), after db.init_app(app):
event_repo = AnalysisEventRepository()
settings_repo = SettingsRepository()
prompt_repo = PromptRepository()
report_repo = ReportRepository()
exclusion_repo = ExclusionRepository()

# Pass repos to services that need them:
sentinel_service = SentinelService(
    llm_call_service=llm_call_service,
    verdict_parser=verdict_parser,
    telegram_notifier=telegram_notifier,
    event_repo=event_repo,
    prompt_repo=prompt_repo,
    exclusion_repo=exclusion_repo,
)
briefing_service = BriefingService(
    llm_call_service=llm_call_service,
    event_repo=event_repo,
    prompt_repo=prompt_repo,
    report_repo=report_repo,
)

app.extensions["services"] = ServiceContainer(
    # ... existing args ...
    event_repo=event_repo,
    settings_repo=settings_repo,
    prompt_repo=prompt_repo,
    report_repo=report_repo,
    exclusion_repo=exclusion_repo,
)
```

### Pattern 5: Updated Service Constructor

**What:** Services add repository parameters and remove all direct `db.session` and `Model.query` calls.

**SentinelService constructor update:**

```python
class SentinelService:
    def __init__(
        self,
        llm_call_service: LLMCallService,
        verdict_parser: Any,
        telegram_notifier: Any,
        event_repo: AnalysisEventRepository,
        prompt_repo: PromptRepository,
        exclusion_repo: ExclusionRepository,
    ) -> None:
        self.llm_call_service = llm_call_service
        self.verdict_parser = verdict_parser
        self.telegram_notifier = telegram_notifier
        self.event_repo = event_repo
        self.prompt_repo = prompt_repo
        self.exclusion_repo = exclusion_repo
        self.log_buffer = LogBuffer(16000, 4000, 600)
```

### Anti-Patterns to Avoid

- **Generic base class:** Do not create `BaseRepository` with `get_by_id()` / `find_all()`. Each repository has only the domain methods it needs.
- **Repositories calling commit:** `db.session.commit()` belongs to the caller. Repositories call `db.session.add()` and `db.session.delete()` only. The one exception is `SettingsRepository.save()` which commits — this is deliberate because Settings mutations are always standalone operations.
- **Repositories importing from services:** Repository files must never import from `app.services.*`. Import direction is always: services → repositories → models → extensions.
- **Constructor-injecting `db`:** Per D-02, repositories use the module-level `db` from `app.extensions`. Do not pass `db` as a constructor argument — it couples the repository to Flask-SQLAlchemy internals that are already globally scoped.

---

## Complete Query Site Inventory

All inline queries identified by file and their target repository method.

### `app/services/sentinel.py` (20 inline calls → AnalysisEventRepository + PromptRepository + ExclusionRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `ExclusionRule.query.filter_by(enabled=True).all()` | `ExclusionRepository.list_enabled()` |
| `PromptTemplate.query.filter_by(key=key.value).first()` (×3) | `PromptRepository.get_by_key(key)` |
| `AnalysisEvent.query.filter(and_(container_id==, status=="excluded", created_at>=)).first()` | `AnalysisEventRepository.find_recent_excluded(container_id, since)` |
| `db.session.add(AnalysisEvent(...excluded...))` + commit | `event_repo.add(event)` + caller commits |
| `db.session.add(event)` + commit (skipped status) | `event_repo.add(event)` + caller commits |
| `AnalysisEvent.query.filter(and_(chunk_hash==, status.notin_, created_at>=)).first()` | `AnalysisEventRepository.find_duplicate_chunk(hash, since)` |
| `db.session.add(event)` + commit (dedup_skipped) | `event_repo.add(event)` + caller commits |
| `AnalysisEvent.query.filter(and_(container_id==, status.in_, created_at>=)).count()` | `AnalysisEventRepository.count_recent_by_container(container_id, since)` |
| `db.session.add(event)` + commit (rate_limited) | `event_repo.add(event)` + caller commits |
| `db.session.add(event)` + commit (llm_error) | `event_repo.add(event)` + caller commits |
| `db.session.add(event)` + commit (parse_error) | `event_repo.add(event)` + caller commits |
| `AnalysisEvent.query.filter(and_(chunk_hash==, alert_sent==True, created_at>=)).first()` | `AnalysisEventRepository.find_alert_duplicate(hash, since)` |
| `AnalysisEvent.query.filter(and_(alert_sent==True, created_at>=)).count()` | `AnalysisEventRepository.count_recent_alerts(since)` |
| `db.session.add(event)` + commit (analyzed) | `event_repo.add(event)` + caller commits |

Note on commit ownership: Sentinel's `process_chunk` currently commits after every early-return and after the final persist. After migration, services call `event_repo.add(event)` and then `db.session.commit()` directly. The repository wraps `add()` but commit stays in the service, per D-01. This preserves the existing atomicity semantics without introducing a Unit of Work abstraction.

### `app/services/briefing.py` (3 calls → AnalysisEventRepository + PromptRepository + ReportRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `AnalysisEvent.query.filter(created_at >= period_start).order_by(asc).all()` | `AnalysisEventRepository.get_for_window(since)` |
| `PromptTemplate.query.filter_by(key=key.value).first()` (×2) | `PromptRepository.get_by_key(key)` |
| `db.session.add(report)` + commit | `report_repo.add(report)` + caller commits |

### `app/api/prompts.py` (5 calls → PromptRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `PromptTemplate.query.order_by(key.asc()).all()` | `PromptRepository.list_all()` |
| `PromptTemplate.query.filter_by(key=key).first()` (×2) | `PromptRepository.get_by_key(key)` |
| `db.session.commit()` (×2) | Caller commits directly (no repo method needed — ORM tracks the mutation) |

### `app/api/reports.py` (2 calls → ReportRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `DailyReport.query.order_by(created_at.desc()).all()` | `ReportRepository.list_all()` |
| `db.session.get(DailyReport, report_id)` | `ReportRepository.get(report_id)` |

### `app/api/exclusions.py` (6 calls → ExclusionRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `ExclusionRule.query.order_by(pattern.asc()).all()` | `ExclusionRepository.list_all()` |
| `ExclusionRule.query.filter_by(container_pattern=pattern).first()` | `ExclusionRepository.find_by_pattern(pattern)` |
| `db.session.add(rule)` + commit | `exclusion_repo.add(rule)` + caller commits |
| `db.session.get(ExclusionRule, rule_id)` | `ExclusionRepository.get(rule_id)` |
| `db.session.delete(rule)` + commit | `exclusion_repo.delete(rule)` + caller commits |

### `app/api/settings.py` (1 call → SettingsRepository)

| Current inline call | Repository method |
|---------------------|-------------------|
| `db.session.commit()` after field mutation | `settings_repo.save()` |

### `app/__init__.py` web routes (15 calls — see REPO-03 note)

| Route function | Queries to migrate |
|----------------|--------------------|
| `dashboard()` | `AnalysisEvent.query.filter(today).all()`, `.order_by.limit(10).all()`, `DailyReport.query.order_by.first()` |
| `settings_page()` | `db.session.commit()` after form post |
| `exclusions_page()` GET | `ExclusionRule.query.order_by.all()` |
| `exclusions_page()` POST | `ExclusionRule.query.filter_by(pattern).first()`, `db.session.add()` + commit |
| `exclusions_delete()` | `db.session.get(ExclusionRule, rule_id)`, `db.session.delete()` + commit |
| `insights_page()` | `AnalysisEvent.query` (filtered, ordered, limited), `db.session.query(container_name).distinct()` |
| `reports_page()` | `DailyReport.query.order_by.all()`, `db.session.get(DailyReport, id)` |
| `prompt_studio_page()` | `PromptTemplate.query.filter_by(key).first()` (×2), `db.session.commit()`, `PromptTemplate.query.order_by.all()` |

These web route queries use the same repository methods as the API routes. The routes access repos via `current_app.extensions["services"].event_repo` etc. (or a typed `get_services()` helper).

### `app/services/coordinator.py` (1 call)

`db.session.commit()` inside `start()` — this persists the initial `SentinelState` runtime status. This one is **not** routed through a repository because `SentinelState` deliberately has no repository (D-07). The call stays as-is.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Session management | Custom session factory, context managers, session pooling | Flask-SQLAlchemy scoped session (`db.session`) | Already present; request-scoped, thread-local, expire_on_commit=False already configured |
| Repository base class | `GenericRepository[T]` with `get_by_id()`, `find_all()` | No base class — domain-named methods per repo | CLAUDE.md explicitly prohibits this; adds wrong abstraction |
| Query builder abstraction | Fluent query builder on top of SQLAlchemy | SQLAlchemy ORM query API directly | SQLAlchemy is already the query builder |

**Key insight:** Repositories in this codebase are thin wrappers around existing SQLAlchemy patterns, not a framework. The value is in centralizing query logic for discoverability and testability, not in introducing a new abstraction layer.

---

## Common Pitfalls

### Pitfall 1: Forgetting `expire_on_commit=False` on New Sessions

**What goes wrong:** `app/extensions.py` configures the Flask-SQLAlchemy session with `expire_on_commit=False`. Repository methods use `db.session` — the same scoped session — so this setting is already in effect. But if a repository introduces its own `Session()` call (e.g., testing if a factory is needed), the new session defaults to `expire_on_commit=True`, causing `DetachedInstanceError` when callers access model attributes after commit.

**How to avoid:** Repositories must always use `db.session` from `app.extensions`, never create their own session. Confirmed by D-02.

**Warning signs:** `DetachedInstanceError: Instance <AnalysisEvent> is not bound to a Session` after any db write.

### Pitfall 2: Circular Import via Model or Service Imports

**What goes wrong:** Repository modules import from `app.models.*` (correct) but may accidentally import from `app.services.*` (wrong). Services that import repositories at module load time risk circular dependency if the repository module also imports from services.

**How to avoid:** Import direction is strictly one-way: `services → repositories → models → extensions`. Repository modules never import from `app.services`. Verify by checking that `app/repositories/analysis_events.py` imports only from `app.extensions` and `app.models.events`.

**Warning signs:** `ImportError: cannot import name 'X' from partially initialized module` at test collection time.

### Pitfall 3: Repositories Owning Commit — Breaking Multi-Step Atomicity

**What goes wrong:** `SentinelService.process_chunk` currently executes 6 code paths, each doing `db.session.add(event)` + `db.session.commit()`. If the repository's `add()` method calls `db.session.commit()` internally, the sentinel's pattern of add-then-commit is preserved — but any future multi-step transaction (write event + write report atomically) becomes impossible because the commit fires too early.

**How to avoid:** Per D-01, `add()` calls `db.session.add(event)` only. The caller (service method) continues to call `db.session.commit()` after the add. No change to existing atomicity — the migration is a rename, not a structural change.

**Warning signs:** If `add()` in a repository calls `db.session.commit()`, any test that asserts on `event.id` after `add()` but before an explicit commit will see `None`.

### Pitfall 4: Breaking Test Injection When ServiceContainer Grows

**What goes wrong:** Tests in `test_sentinel_pipeline.py` inject doubles by doing `sentinel.telegram_notifier = DummyTelegram()` and `sentinel.llm_call_service._client = DummyLLM()` — attribute assignment on the service object after it is fetched from `app.extensions["services"]`. Adding repo attributes to `ServiceContainer` does not break these tests. But if a test is constructing a `SentinelService` manually (not via `create_app()`), it will now fail with a missing `event_repo` positional argument.

**How to avoid:** All tests use `create_app()` via `_build_app()` — none construct `SentinelService` directly. Verify this before changing the constructor signature. If any test does construct services directly, update the test to also pass a repo instance (can use the real repo class since tests use a real SQLite DB).

**Warning signs:** `TypeError: __init__() missing required argument: 'event_repo'` in any test.

### Pitfall 5: Web Route Queries Left Behind (REPO-03 violation)

**What goes wrong:** REPO-03 requires zero inline queries in "services and routes." The `app/__init__.py` web routes have ~15 inline queries but are easy to overlook because they are closures inside `_register_web_routes()`, not in `app/api/`. If these are not migrated, REPO-03 is technically not satisfied, and the verification check (`grep -r 'session.query\|\.query\.filter\|session.execute'`) will still find hits.

**How to avoid:** The query site inventory above lists all 15 web route queries. Route handlers access repos via `current_app.extensions["services"].event_repo` (or via `get_services()` helper). All web routes use the same repo methods already defined for the API routes — no new repo methods are needed for the web routes.

**Warning signs:** Post-phase grep for `\.query\.filter\|session\.query\|session\.execute` in `app/api/` and `app/services/` returns zero but `app/__init__.py` still has hits.

---

## Code Examples (Verified Against Existing Codebase)

### Migrating a Multi-Condition Filter (Dedup Check)

Before (inline in `sentinel.py`):
```python
already_analyzed = AnalysisEvent.query.filter(
    and_(
        AnalysisEvent.chunk_hash == event.chunk_hash,
        AnalysisEvent.status.notin_(["skipped"]),
        AnalysisEvent.created_at >= cutoff,
    )
).first()
```

After (in service, via repository):
```python
# In AnalysisEventRepository:
def find_duplicate_chunk(self, chunk_hash: str, since: datetime) -> AnalysisEvent | None:
    return AnalysisEvent.query.filter(
        and_(
            AnalysisEvent.chunk_hash == chunk_hash,
            AnalysisEvent.status.notin_(["skipped"]),
            AnalysisEvent.created_at >= since,
        )
    ).first()

# In SentinelService.process_chunk():
already_analyzed = self.event_repo.find_duplicate_chunk(event.chunk_hash, cutoff)
```

### Migrating an Add + Commit Pattern

Before (inline in `sentinel.py`):
```python
db.session.add(event)
db.session.commit()
return event
```

After:
```python
# In SentinelService.process_chunk():
self.event_repo.add(event)   # repository adds to session
db.session.commit()           # service owns the commit (D-01)
return event
```

### Migrating Settings Commit

Before (inline in `api/settings.py`):
```python
for key, value in payload.items():
    if key in _ALLOWED_FIELDS:
        setattr(settings, key, value)
db.session.commit()
```

After:
```python
for key, value in payload.items():
    if key in _ALLOWED_FIELDS:
        setattr(settings, key, value)
container.settings_repo.save()   # wraps db.session.commit()
```

### Test Injection (No Change Required)

Existing tests inject doubles on the service instance after fetching it from the container — this pattern is unaffected by adding repo attributes:

```python
# test_sentinel_pipeline.py (unchanged pattern)
sentinel = app.extensions["services"].sentinel
sentinel.llm_call_service._client = DummyLLM()   # still works
sentinel.telegram_notifier = DummyTelegram()       # still works
```

Repositories use the same real SQLite test DB that `create_app()` creates via `db.create_all()` — no fake repo needed for the existing integration test style.

---

## Migration Execution Order

Recommended sequence to keep all 31 tests green at each step:

1. **Create `app/repositories/` package with all 5 repo classes** — no call sites updated yet. Tests still pass (no behavior change).

2. **Add repo attributes to `ServiceContainer`** — instantiate repos in `create_app()`, pass to `ServiceContainer`. Update `SentinelService`, `BriefingService` constructors to accept repos. Tests pass (repos are wired but services still use inline queries).

3. **Migrate `SentinelService`** — replace all 20 inline query/session calls. Run 31 tests. This is the highest-risk step. Commit only when green.

4. **Migrate `BriefingService`** — replace 3 inline calls. Run 31 tests.

5. **Migrate `app/api/` blueprints** — migrate exclusions, prompts, reports, settings in any order. Each is a small file (2-6 calls). Run 31 tests after each file.

6. **Migrate `app/__init__.py` web routes** — replace ~15 inline calls. Route handlers use `current_app.extensions["services"].event_repo` etc. Run 31 tests.

7. **Verify REPO-03** — grep for `\.query\.filter\|\.session\.query\|\.session\.execute` in `app/services/` and `app/api/` and `app/__init__.py`. Expect zero results (excluding `app/repositories/` and `app/models/`).

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — this phase is pure Python class extraction using libraries already in the installed environment).

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| Active Record (models with query class methods) | Repository (query logic in separate class) | DockSentinel currently uses Active Record via `Model.query.*`; repos move queries out while models remain unchanged |
| Direct `db.session` in route handlers | Route → Repository | Standard layered architecture pattern; prevents routes from becoming "fat controllers" |

**Deprecated patterns (to eliminate in this phase):**
- `Model.query.filter_by(...)` in service files
- `db.session.add()` + `db.session.commit()` scattered across route handlers
- `Model.query.filter_by(...)` in route closures in `app/__init__.py`

---

## Open Questions

1. **REPO-03 scope: include `app/__init__.py` web routes?**
   - What we know: CONTEXT.md "Claude's Discretion" says both approaches are valid — migrate web routes in Phase 2 or defer to Phase 4 (Blueprint extraction).
   - What's unclear: Whether the planner should include the 15 web route queries in Phase 2 tasks or defer them.
   - Recommendation: Include in Phase 2. The repo methods are already defined for the API equivalents (same models, same queries). Deferring creates a confusing split where API routes use repos but web routes still use inline queries, making REPO-03 verification ambiguous.

2. **`SettingsRepository.save()` — commit or not?**
   - What we know: D-01 says repos don't commit. But `SettingsRepository.save()` is the canonical way to persist settings mutations — and settings mutations are always standalone (no multi-step atomicity needed).
   - What's unclear: Whether to make `save()` commit (convenience) or leave commit to the caller.
   - Recommendation: `save()` commits. Settings is a special case: there is no multi-step flow involving settings that requires deferred commit. Making callers do `db.session.commit()` directly after `settings_repo.save()` would be redundant. The CONTEXT.md example for SettingsRepository shows `save()` as a method, implying it completes the operation.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `app/services/sentinel.py`, `app/services/briefing.py`, `app/api/*.py`, `app/__init__.py`, `app/models/*.py`, `app/container.py`, `app/extensions.py`
- `.planning/research/ARCHITECTURE.md` — Repository Layer section, Component Boundaries table, Data Flow diagrams
- `.planning/research/PITFALLS.md` — Pitfall 6 (DetachedInstanceError), Pitfall 1 (circular imports)
- `.planning/phases/02-repository-layer/02-CONTEXT.md` — All locked decisions (D-01 through D-09)
- CLAUDE.md — "Don't use a generic repository base class" directive

### Secondary (MEDIUM confidence)
- Architecture Patterns with Python (Cosmic Python) — Repository Pattern chapter: https://www.cosmicpython.com/book/chapter_02_repository.html (verifies domain-named methods, session ownership at service layer)

---

## Metadata

**Confidence breakdown:**
- Query site inventory: HIGH — all sites identified by direct file inspection
- Repository method signatures: HIGH — derived mechanically from existing inline queries
- Session ownership pattern: HIGH — locked by D-01, matches `expire_on_commit=False` in extensions.py
- Migration order: HIGH — dependency graph is clear (repos must exist before services wire to them)
- REPO-03 web route scope: MEDIUM — planner decision needed (see Open Questions #1)

**Research date:** 2026-04-04
**Valid until:** Stable — no external libraries involved; valid until codebase changes
