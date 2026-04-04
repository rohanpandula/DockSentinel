<!-- GSD:project-start source:PROJECT.md -->
## Project

**DockSentinel Total Refactor**

DockSentinel is a self-hosted AIOps observability agent for Docker environments. It monitors container logs in real-time, uses LLMs (API or CLI backends) for semantic triage, sends Telegram alerts, and generates nightly health briefings. The MVP is complete (v0.2) with a Flask/Jinja2 dashboard, SQLite persistence, and 31 tests across 10 test files (~3,309 LOC total).

This milestone is a full architectural refactor of the existing MVP codebase to eliminate tech debt, improve testability, and lay a clean foundation for the features in ROADMAP.md (React SPA, fix suggestions, notification center, RAG). No new features — this is purely structural.

**Core Value:** Every refactoring change must keep the existing API contract intact (all endpoints continue to work) and all 31 tests passing — structure improves without breaking behavior.

### Constraints

- **API contract**: All existing endpoints in README must continue to work with identical request/response shapes
- **Test stability**: Existing 31 tests must pass throughout every phase
- **Tech stack**: Python 3.12, Flask, SQLAlchemy, Pydantic v2, SQLite, Docker, APScheduler — no new frameworks
- **Incremental delivery**: Each phase must be independently shippable
- **No new features**: Purely structural refactoring — same behavior, better architecture
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Baseline: What Already Exists (Do Not Change)
| Library | Pinned Version | Current Latest | Status |
|---------|---------------|----------------|--------|
| Flask | 3.0.3 | 3.1.3 | Minor bump available — safe to upgrade |
| Flask-SQLAlchemy | 3.1.1 | 3.1.1 | Current |
| SQLAlchemy | 2.0.36 | 2.0.49 | Patch bumps available — safe to upgrade |
| Pydantic | 2.10.6 | 2.12.5 | Minor bump available — safe to upgrade |
| pytest | 8.3.4 | 9.0.2 | Major bump — hold until tests pass |
| APScheduler | 3.10.4 | — | Keep as-is |
## Recommended Additions for This Refactor
### 1. Database Migrations — Alembic
# Configure alembic/env.py to import your SQLAlchemy Base and models
# Generate baseline migration from current schema:
# Stamp the existing database so Alembic doesn't try to re-create tables:
### 2. Request/Response Validation — Flask-Pydantic
- `flask-pydantic-spec` — adds OpenAPI generation overhead, overkill for this refactor
- `marshmallow` — separate serialization library when Pydantic v2 already does the job
- Manual `request.get_json()` + Pydantic `.model_validate()` inline in routes — works, but Flask-Pydantic centralizes error handling and reduces boilerplate across all endpoints consistently
### 3. Test Coverage Measurement — pytest-cov
# pytest.ini additions
## Patterns (No New Libraries Required)
### 4. Repository Pattern — SQLAlchemy Sessions
# app/repositories/events.py
- Don't use a "generic repository" base class with magical `get_by_id`, `find_all` — it leaks the wrong abstraction. Each repository has domain-specific query methods.
- Don't import `db.session` directly from Flask-SQLAlchemy globals inside service classes — this couples the service to the Flask request context and makes unit testing painful.
### 5. Dependency Injection — Typed Dataclass Container (Composition Root)
# app/container.py
# app/__init__.py  (app factory)
# In a route:
### 6. Service Layer — Thin Orchestration Classes
# app/services/llm_call.py
### 7. Config Decomposition — Domain-Specific Pydantic Models
# app/config.py
### 8. API Pagination — Offset for This Scale
# Query pattern
## Alert Strategy Pattern — Standard Library Only
# app/services/alerts.py
## Full Dependency Delta
# ADD (runtime)
# ADD (dev/test only)
# OPTIONAL UPGRADES (safe, not required for refactor to succeed)
# Flask: 3.0.3 → 3.1.3
# SQLAlchemy: 2.0.36 → 2.0.49
# pydantic: 2.10.6 → 2.12.5
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
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
