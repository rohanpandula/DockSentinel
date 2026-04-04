# Technology Stack

**Project:** DockSentinel — Flask/SQLAlchemy/Pydantic v2 Architectural Refactor
**Researched:** 2026-04-04
**Mode:** Ecosystem — "What's the standard 2025/2026 stack for refactoring a Flask/SQLAlchemy/Pydantic v2 project?"

---

## Baseline: What Already Exists (Do Not Change)

The existing requirements.txt pins these. The refactor adds tooling around them — it does not replace them.

| Library | Pinned Version | Current Latest | Status |
|---------|---------------|----------------|--------|
| Flask | 3.0.3 | 3.1.3 | Minor bump available — safe to upgrade |
| Flask-SQLAlchemy | 3.1.1 | 3.1.1 | Current |
| SQLAlchemy | 2.0.36 | 2.0.49 | Patch bumps available — safe to upgrade |
| Pydantic | 2.10.6 | 2.12.5 | Minor bump available — safe to upgrade |
| pytest | 8.3.4 | 9.0.2 | Major bump — hold until tests pass |
| APScheduler | 3.10.4 | — | Keep as-is |

Sources: PyPI verified 2026-04-04. Confidence: HIGH.

---

## Recommended Additions for This Refactor

### 1. Database Migrations — Alembic

**Add:** `alembic==1.18.4`

**Why:** The project currently runs raw SQL DDL inside the Flask app factory (`app/__init__.py`). Alembic is the canonical SQLAlchemy migration tool — same author, same ORM, first-class support for auto-generating migrations from model changes. It replaces the hardcoded `CREATE TABLE IF NOT EXISTS` calls with a proper version-controlled migration history.

**Critical SQLite configuration — `render_as_batch=True`:** SQLite cannot execute most `ALTER TABLE` statements. Alembic's batch migration mode works around this by using a move-and-copy strategy (create temp table → copy data → drop original → rename). Set `render_as_batch=True` in `env.py`'s `run_migrations_online()` and in the `MigrationContext` configuration. This setting is safe to leave enabled universally because non-SQLite backends ignore it and use standard ALTER instead.

**Setup for existing project (not greenfield):**
```bash
alembic init alembic
# Configure alembic/env.py to import your SQLAlchemy Base and models
# Generate baseline migration from current schema:
alembic revision --autogenerate -m "baseline"
# Stamp the existing database so Alembic doesn't try to re-create tables:
alembic stamp head
```

**What NOT to use:** Flask-Migrate (wraps Alembic but adds Flask-specific magic and a CLI layer that's unnecessary overhead for a project that already uses plain SQLAlchemy rather than Flask-SQLAlchemy's declarative base). Plain Alembic gives full control.

Confidence: HIGH — official Alembic docs verified.

---

### 2. Request/Response Validation — Flask-Pydantic

**Add:** `Flask-Pydantic==0.14.0`

**Why:** Pydantic v2 is already in the stack (used by `VerdictParser`). Flask-Pydantic extends this to HTTP boundaries via a `@validate` decorator that parses and validates request bodies, query params, and serializes responses — replacing manual `request.json` access and `jsonify()` calls. The `pallets-eco/flask-pydantic` fork (v0.14.0, December 2025) is the maintained version with confirmed Pydantic v2 compatibility (PR #92 merged Pydantic v2 support; PR #105 April 2025 added further fixes).

**Pattern to follow:**
```python
from flask_pydantic import validate
from pydantic import BaseModel

class InsightsQueryParams(BaseModel):
    page: int = 1
    page_size: int = 50
    container: str | None = None

@bp.get("/insights")
@validate()
def list_insights(query: InsightsQueryParams):
    # query is already parsed and validated
    ...
```

**What NOT to use:**
- `flask-pydantic-spec` — adds OpenAPI generation overhead, overkill for this refactor
- `marshmallow` — separate serialization library when Pydantic v2 already does the job
- Manual `request.get_json()` + Pydantic `.model_validate()` inline in routes — works, but Flask-Pydantic centralizes error handling and reduces boilerplate across all endpoints consistently

Confidence: MEDIUM — PyPI version confirmed; Pydantic v2 compatibility inferred from GitHub PR history, not from running the library directly.

---

### 3. Test Coverage Measurement — pytest-cov

**Add:** `pytest-cov==7.1.0`

**Why:** The project estimates 40-50% coverage but has no tooling to measure it. pytest-cov integrates directly with pytest and produces line/branch coverage reports. The target is 80%+. This is measurement tooling for the refactor's quality gate, not a runtime dependency.

```ini
# pytest.ini additions
[pytest]
addopts = --cov=app --cov-report=term-missing --cov-fail-under=80
```

**What NOT to add:** `coverage[toml]` directly — pytest-cov wraps it and is the pytest-native interface.

Confidence: HIGH — PyPI version 7.1.0 verified 2026-04-04.

---

## Patterns (No New Libraries Required)

These are architectural patterns implemented with what's already in the stack. They require no new dependencies.

### 4. Repository Pattern — SQLAlchemy Sessions

**Pattern:** Thin repository classes that own all database access for one model. Each repository receives a SQLAlchemy `Session` via constructor injection. No ORM session leaking into service layer.

```python
# app/repositories/events.py
from sqlalchemy.orm import Session
from app.models.events import AnalysisEvent

class EventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_recent(self, limit: int = 100) -> list[AnalysisEvent]:
        return (
            self._session.query(AnalysisEvent)
            .order_by(AnalysisEvent.created_at.desc())
            .limit(limit)
            .all()
        )

    def save(self, event: AnalysisEvent) -> AnalysisEvent:
        self._session.add(event)
        self._session.flush()
        return event
```

**Why this shape:** `flush()` not `commit()` — the service layer or request context owns transaction boundaries, not the repository. This is the standard pattern from "Architecture Patterns with Python" (Cosmic Python), verified against the SQLAlchemy community discussion thread (GitHub sqlalchemy/sqlalchemy #11354).

**What NOT to do:**
- Don't use a "generic repository" base class with magical `get_by_id`, `find_all` — it leaks the wrong abstraction. Each repository has domain-specific query methods.
- Don't import `db.session` directly from Flask-SQLAlchemy globals inside service classes — this couples the service to the Flask request context and makes unit testing painful.

Confidence: MEDIUM — pattern verified against multiple authoritative sources (Cosmic Python, SQLAlchemy discussions). No single official SQLAlchemy doc prescribes this exact shape.

---

### 5. Dependency Injection — Typed Dataclass Container (Composition Root)

**Pattern:** A plain Python `@dataclass` acts as the service container. It is built once at application startup in the app factory and stored in `app.extensions`. Routes and services receive typed references — no string-keyed dict.

```python
# app/container.py
from dataclasses import dataclass
from app.repositories.events import EventRepository
from app.services.llm_call import LLMCallService
from app.services.sentinel import SentinelService

@dataclass
class ServiceContainer:
    llm: LLMCallService
    sentinel: SentinelService
    event_repo: EventRepository
    # ... other services

# app/__init__.py  (app factory)
def create_app(config=None) -> Flask:
    app = Flask(__name__)
    # ... setup
    container = ServiceContainer(
        llm=LLMCallService(...),
        sentinel=SentinelService(...),
        event_repo=EventRepository(db.session),
    )
    app.extensions["container"] = container
    return app

# In a route:
def get_container() -> ServiceContainer:
    return current_app.extensions["container"]
```

**Why a dataclass over a dict:** Type-safe attribute access — `container.llm` vs `app.extensions["services"]["llm"]`. IDEs and mypy can catch attribute errors. The container itself is a value object, not a registry.

**Why NOT Flask-Injector or dependency-injector library:** The constraint is "no new frameworks." Both libraries add decorator-based magic that obscures the wiring and complicates testing. Manual composition root is explicit, debuggable, and has zero runtime overhead. "Architecture Patterns with Python" Chapter 13 endorses this exact approach.

Confidence: MEDIUM — pattern canonical per Cosmic Python; no official Flask doc prescribes this. Verified against multiple 2024-2025 sources.

---

### 6. Service Layer — Thin Orchestration Classes

**Pattern:** Service classes orchestrate repositories and downstream services. They do not contain SQL. They receive all dependencies via `__init__`. Business logic (dedup, rate limiting, LLM routing) lives in the service, not the route.

```python
# app/services/llm_call.py
class LLMCallService:
    def __init__(
        self,
        llm_client: LLMClient,
        cli_runner: CLIBackendRunner,
        config: LLMConfig,
    ) -> None:
        self._client = llm_client
        self._cli = cli_runner
        self._config = config

    def call(self, prompt: str, system: str) -> str:
        # Single place for all LLM invocation logic
        ...
```

Routes call services. Services call repositories. Repositories call the ORM. No layer skips a level.

**What NOT to do:** Don't pass `app` or `current_app` into service `__init__` — this couples services to Flask lifecycle and makes them untestable outside a request context.

Confidence: HIGH — this is the standard layered architecture endorsed by Flask docs, Cosmic Python, and consistent across all 2025 sources.

---

### 7. Config Decomposition — Domain-Specific Pydantic Models

**Pattern:** Break the `Settings` god object (25+ fields) into domain-scoped `BaseSettings`-style Pydantic models. Since this is not a FastAPI project, use plain Pydantic `BaseModel` or `@dataclass` loaded from the database row.

```python
# app/config.py
from pydantic import BaseModel

class LLMConfig(BaseModel):
    backend: str
    model: str
    api_key: str | None = None
    timeout: int = 30

class AlertConfig(BaseModel):
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    cooldown_seconds: int = 300

class CallReductionConfig(BaseModel):
    prefilter_enabled: bool = True
    dedup_window_seconds: int = 60
    rate_limit_per_minute: int = 10
```

Each config class is passed to the service that needs it — `LLMCallService` gets `LLMConfig`, `TelegramService` gets `AlertConfig`. No service receives the entire settings blob.

Confidence: HIGH — Pydantic v2 `BaseModel` is already used in this project. This is a structural decomposition, not a new capability.

---

### 8. API Pagination — Offset for This Scale

**Pattern:** Use offset pagination (`page` + `page_size`) for all list endpoints. Cursor/keyset pagination is superior for large datasets with frequent inserts, but at DockSentinel's scale (single-user, local SQLite, thousands of events at most), offset pagination is appropriate and far simpler to implement.

```python
class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool

# Query pattern
def paginate(query, page: int, page_size: int):
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return items, total
```

**Hard cap:** Enforce `page_size <= 200` at the Pydantic model level to prevent unbounded queries.

**What NOT to use:** Cursor pagination is overkill here — it requires stable sort keys, opaque token encoding, and breaks direct page navigation. Keyset pagination has the same complexity. Reserve these for ROADMAP phases where data volume grows.

Confidence: HIGH — pagination strategy matched to scale; multiple 2025 sources confirm offset-for-small-datasets as correct.

---

## Alert Strategy Pattern — Standard Library Only

**Pattern:** `abc.ABC` + `abc.abstractmethod` for the `AlertStrategy` interface. No library needed.

```python
# app/services/alerts.py
from abc import ABC, abstractmethod

class AlertStrategy(ABC):
    @abstractmethod
    def send(self, message: str, severity: str) -> None: ...

class TelegramAlertStrategy(AlertStrategy):
    def send(self, message: str, severity: str) -> None:
        # existing Telegram logic
        ...
```

This creates the seam for ROADMAP Phase 3 (Slack/email/Discord) without building it now. The `SentinelService` pipeline calls `strategy.send()`, not `telegram_service.send_alert()` directly.

Confidence: HIGH — Python stdlib `abc` module, zero new dependencies.

---

## Full Dependency Delta

What changes from the current `requirements.txt`:

```
# ADD (runtime)
Flask-Pydantic==0.14.0
alembic==1.18.4

# ADD (dev/test only)
pytest-cov==7.1.0

# OPTIONAL UPGRADES (safe, not required for refactor to succeed)
# Flask: 3.0.3 → 3.1.3
# SQLAlchemy: 2.0.36 → 2.0.49
# pydantic: 2.10.6 → 2.12.5
```

No runtime libraries are removed. No framework migrations. Total new production dependencies: 2.

---

## What NOT to Add (and Why)

| Library | Reason to Avoid |
|---------|----------------|
| FastAPI | Framework migration explicitly out of scope; introduces async complexity and breaks existing sync test suite |
| Flask-Migrate | Thin Flask wrapper around Alembic that adds a CLI layer and Flask app context dependency — plain Alembic gives identical functionality with more control |
| dependency-injector | Framework-level magic for a problem solvable with a 10-line dataclass; adds learning curve and decorator overhead |
| Flask-Injector | Same objection as dependency-injector; violates "no new frameworks" constraint |
| marshmallow | Pydantic v2 already in stack; running two serialization libraries is a maintenance burden |
| SQLModel | Merges SQLAlchemy ORM and Pydantic models — appealing but would require rewriting all existing ORM models, violating the "incremental delivery" constraint |
| httpx (already present) | Already in requirements — no action needed |

---

## Sources

- Alembic 1.18.4 documentation — https://alembic.sqlalchemy.org/en/latest/batch.html (batch migrations for SQLite)
- Alembic 1.18.4 on PyPI — https://pypi.org/project/alembic/ (version verified 2026-04-04)
- SQLAlchemy 2.0.49 on PyPI — https://pypi.org/project/SQLAlchemy/ (version verified 2026-04-04)
- Flask 3.1.3 on PyPI — https://pypi.org/project/Flask/ (version verified 2026-04-04)
- Pydantic 2.12.5 on PyPI — https://pypi.org/project/pydantic/ (version verified 2026-04-04)
- Flask-Pydantic 0.14.0 on PyPI — https://pypi.org/project/Flask-Pydantic/ (version verified 2026-04-04)
- Flask-Pydantic GitHub (pallets-eco) — https://github.com/pallets-eco/flask-pydantic (Pydantic v2 compatibility)
- pytest-cov 7.1.0 on PyPI — https://pypi.org/project/pytest-cov/ (version verified 2026-04-04)
- pytest 9.0.2 on PyPI — https://pypi.org/project/pytest/ (version verified 2026-04-04)
- Architecture Patterns with Python (Cosmic Python) — Service Layer chapter: https://www.cosmicpython.com/book/chapter_04_service_layer.html
- Architecture Patterns with Python (Cosmic Python) — Repository Pattern: https://www.cosmicpython.com/book/chapter_02_repository.html
- Flask best practices for 2025 (DEV Community) — https://dev.to/gajanan0707/how-to-structure-a-large-flask-application-best-practices-for-2025-9j2
- API Pagination strategies 2025 — https://medium.com/@kuipasta1121/api-pagination-us-flask-offset-vs-cursor-based-approaches-b2e5327b0056
- SQLAlchemy repository pattern discussion — https://github.com/sqlalchemy/sqlalchemy/discussions/11354
- pytest-flask-sqlalchemy plugin — https://pypi.org/project/pytest-flask-sqlalchemy/
