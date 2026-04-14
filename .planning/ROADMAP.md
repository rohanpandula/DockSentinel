# Roadmap: DockSentinel Total Refactor

## Overview

This milestone transforms the DockSentinel MVP from a working-but-tangled Flask monolith into a cleanly layered architecture. The refactor proceeds in five dependency-ordered phases: extract and unify LLM invocation logic first (no schema impact, immediate deduplication), then wire a typed service container (unblocks all downstream injection), then isolate all DB access behind repositories (enables testable services), then replace brittle startup SQL with Alembic (clean migration history), then complete service decomposition, Blueprint extraction, and quality hardening. The API contract remains intact and all 31 tests stay green throughout every phase.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Extract LLMCallService, wire typed ServiceContainer, decompose Settings god object (completed 2026-04-04)
- [ ] **Phase 2: Repository Layer** - Centralize all ORM queries behind typed repository classes
- [x] **Phase 3: Alembic Migration Infrastructure** - Replace hardcoded ALTER TABLE with versioned Alembic migrations (completed 2026-04-05)
- [ ] **Phase 4: Service Decomposition and Blueprint** - Extract AlertService, TelegramAlertStrategy, and web Blueprint
- [x] **Phase 5: API Quality and Hardening** - Pydantic validation, pagination, test coverage gate, Docker hardening (completed 2026-04-14)

## Phase Details

### Phase 1: Foundation
**Goal**: The codebase has a single point of LLM invocation, typed dependency access throughout the app, and domain-scoped config objects — with zero schema changes and all 31 tests passing
**Depends on**: Nothing (first phase)
**Requirements**: SRVC-01, SRVC-02, DI-01, DI-02, DI-03, CFG-01, CFG-02, CFG-03
**Success Criteria** (what must be TRUE):
  1. A single `LLMCallService` class exists and is the only place `_call_llm` logic runs — sentinel.py, briefing.py, and api/settings.py no longer contain their own LLM invocation methods
  2. `app.extensions["services"]` is backed by a typed `ServiceContainer` dataclass — accessing a service via a misspelled string key raises an `AttributeError` at attribute access time, not a `KeyError` at runtime
  3. Five domain-specific frozen config dataclasses (`LLMConfig`, `AlertConfig`, `CallReductionConfig`, `TelegramConfig`, `CLIConfig`) exist and services accept them instead of the raw Settings singleton
  4. All 31 existing tests pass with no modifications to test logic
**Plans**: 3 plans

Plans:
- [x] 01-01-PLAN.md — Extract LLMCallService, wire into sentinel/briefing/settings API, update test injection
- [x] 01-02-PLAN.md — Create ServiceContainer dataclass, migrate all 23 string-key access sites
- [x] 01-03-PLAN.md — Create five frozen config dataclasses, update LLMCallService to accept LLMConfig

### Phase 2: Repository Layer
**Goal**: All SQLAlchemy ORM queries are encapsulated in named repository classes — no service or route handler contains inline query calls
**Depends on**: Phase 1
**Requirements**: REPO-01, REPO-02, REPO-03
**Success Criteria** (what must be TRUE):
  1. `AnalysisEventRepository`, `SettingsRepository`, `PromptRepository`, `ReportRepository`, and `ExclusionRepository` classes exist under `app/repositories/`
  2. Searching the codebase for inline `.query.filter`, `.session.execute`, or `.session.query` calls inside `app/services/` and `app/api/` yields zero results
  3. All 31 existing tests pass with no modifications to test logic
**Plans**: 3 plans

Plans:
- [x] 02-01-PLAN.md — Create 5 repository classes, extend ServiceContainer, wire in create_app()
- [x] 02-02-PLAN.md — Migrate SentinelService and BriefingService to use injected repositories
- [ ] 02-03-PLAN.md — Migrate API routes and web routes to use repositories via container

### Phase 3: Alembic Migration Infrastructure
**Goal**: Database schema evolution is managed by Alembic — the brittle `_ensure_settings_schema_compat` function is deleted and `db.create_all()` is gated to test environments only
**Depends on**: Phase 2
**Requirements**: MIG-01, MIG-02, MIG-03, MIG-04
**Success Criteria** (what must be TRUE):
  1. `alembic upgrade head` runs successfully against both a fresh database and an existing v0.2 database without data loss
  2. `_ensure_settings_schema_compat` no longer exists in the codebase
  3. `db.create_all()` only runs when `TESTING=True` — production startup uses `alembic upgrade head` in the Docker entrypoint
  4. All 31 existing tests pass with no modifications to test logic
**Plans**: 2 plans

Plans:
- [x] 03-01-PLAN.md — Initialize Alembic with SQLite batch mode, create baseline and settings compat migrations
- [x] 03-02-PLAN.md — Gate db.create_all() to TESTING, delete compat function, update Docker entrypoint

### Phase 4: Service Decomposition and Blueprint
**Goal**: Alert logic lives in a dedicated `AlertService` behind an `AlertStrategy` protocol, web routes live in a Blueprint, and `app/__init__.py` is reduced to pure wiring
**Depends on**: Phase 3
**Requirements**: SRVC-03, SRVC-04, APP-01, APP-02, APP-03
**Success Criteria** (what must be TRUE):
  1. `AlertService` exists with an `AlertStrategy` protocol — `TelegramAlertStrategy` implements it, and `SentinelService` no longer contains any alert-sending logic
  2. All web routes are registered via a Blueprint in `app/web/routes.py` — every existing URL pattern and endpoint name works identically
  3. `app/__init__.py` is under 100 LOC and contains only app factory wiring
  4. All 31 existing tests pass with no modifications to test logic
**Plans**: 4 plans

Plans:
- [x] 04-01-PLAN.md — Extract AlertService/AlertStrategy/TelegramAlertStrategy, rewire SentinelService + ServiceContainer + factory, swap test seam
- [x] 04-02-PLAN.md — Extract composition root (app/composition.py::build_container) and default seeding (app/bootstrap.py::seed_defaults)
- [x] 04-03-PLAN.md — Extract web routes to app/web/routes.py Blueprint with explicit endpoint= kwargs; rename/expand _register_blueprints
- [x] 04-04-PLAN.md — Final trim of app/__init__.py to ≤90 LOC + phase acceptance matrix + human UI smoke test

### Phase 5: API Quality and Hardening
**Goal**: All list endpoints have Pydantic-validated responses and pagination, test coverage is measured and gated at 80%+, and Docker runs securely with a health check
**Depends on**: Phase 4
**Requirements**: API-01, API-02, API-03, API-04, TEST-01, TEST-02, TEST-03, TEST-04, DOCK-01, DOCK-02, DOCK-03, DOCK-04
**Success Criteria** (what must be TRUE):
  1. `GET /api/insights` and `GET /api/reports` accept `offset`, `limit`, and (for insights) `sort` parameters — existing callers without these parameters receive unchanged responses
  2. All API list endpoints return responses that pass Pydantic v2 schema validation — serialization regressions are caught at test time
  3. `pytest --cov` reports 80%+ coverage across service and API modules, and the CI gate fails the build if coverage drops below that threshold
  4. The Docker container starts as a non-root user and the `docker-compose up` health check reports healthy within 30 seconds
  5. All 31 existing tests plus new integration tests pass
**Plans**: 3 plans

Plans:
- [x] 05-01-PLAN.md — app/schemas/ package + Flask-Pydantic validation + pagination on /api/insights and /api/reports + error envelope remap
- [x] 05-02-PLAN.md — pytest-cov gate at 80%, shared tests/conftest.py fixtures, pipeline integration test + pagination/schema parity tests
- [x] 05-03-PLAN.md — Docker non-root user, /api/health HEALTHCHECK, named volume, Codex/Gemini CLI path relocation

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete   | 2026-04-04 |
| 2. Repository Layer | 2/3 | Executing  |  |
| 3. Alembic Migration Infrastructure | 2/2 | Complete   | 2026-04-05 |
| 4. Service Decomposition and Blueprint | 0/4 | Planned | - |
| 5. API Quality and Hardening | 3/3 | Complete   | 2026-04-14 |
