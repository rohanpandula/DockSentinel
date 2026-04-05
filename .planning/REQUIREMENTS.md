# Requirements: DockSentinel Total Refactor

**Defined:** 2026-04-04
**Core Value:** Every refactoring change must keep the existing API contract intact and all 31 tests passing — structure improves without breaking behavior.

## v1 Requirements

Requirements for this refactor milestone. Each maps to roadmap phases.

### Service Extraction

- [x] **SRVC-01**: LLM invocation logic consolidated into a single LLMCallService class, eliminating duplication across sentinel.py, briefing.py, and api/settings.py
- [x] **SRVC-02**: SentinelService and BriefingService use the shared LLMCallService instead of private _call_llm methods
- [ ] **SRVC-03**: AlertService extracted from SentinelService with AlertStrategy protocol for transport abstraction
- [ ] **SRVC-04**: TelegramAlertStrategy implements the AlertStrategy protocol, replacing hardcoded Telegram calls in SentinelService

### Dependency Injection

- [x] **DI-01**: Typed ServiceContainer dataclass replaces app.extensions["services"] string-keyed dict
- [x] **DI-02**: All route handlers and services access dependencies via typed ServiceContainer attributes
- [x] **DI-03**: Test fixtures inject dependencies via the typed ServiceContainer (shim maintained during transition)

### Configuration

- [x] **CFG-01**: Settings god object decomposed into domain-specific config classes (LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig)
- [x] **CFG-02**: Config classes are frozen dataclasses constructed from the single Settings ORM row (DB schema unchanged)
- [x] **CFG-03**: Services accept domain-specific config objects instead of the raw Settings singleton

### Data Access

- [x] **REPO-01**: AnalysisEventRepository encapsulates all AnalysisEvent ORM queries currently scattered across services and routes
- [x] **REPO-02**: SettingsRepository, PromptRepository, ReportRepository, ExclusionRepository created for remaining models
- [x] **REPO-03**: No service or route handler contains inline SQLAlchemy query calls after repository migration

### Migration Infrastructure

- [ ] **MIG-01**: Alembic initialized with render_as_batch=True for SQLite compatibility
- [ ] **MIG-02**: Initial migration generated and existing databases stamped (alembic stamp head)
- [ ] **MIG-03**: Hardcoded _ensure_settings_schema_compat ALTER TABLE statements replaced by Alembic revisions
- [ ] **MIG-04**: db.create_all() gated to TESTING=True; production uses alembic upgrade head

### App Structure

- [ ] **APP-01**: Web routes extracted from app/__init__.py into a dedicated Blueprint
- [ ] **APP-02**: app/__init__.py reduced to pure app factory wiring (~80 LOC)
- [ ] **APP-03**: All existing URL patterns and endpoint names preserved after Blueprint extraction

### API Quality

- [ ] **API-01**: Pydantic v2 request/response models added to all API list endpoints
- [ ] **API-02**: GET /api/insights supports offset/limit/sort pagination parameters
- [ ] **API-03**: GET /api/reports supports offset/limit pagination parameters
- [ ] **API-04**: All existing API endpoints return identical response shapes (backward compatibility)

### Test Infrastructure

- [ ] **TEST-01**: Shared pytest fixtures extracted to tests/conftest.py (app factory, client, DB session)
- [ ] **TEST-02**: Integration tests added for the full sentinel pipeline (prefilter → dedup → rate limit → LLM → alert)
- [ ] **TEST-03**: pytest-cov configured with minimum coverage threshold (80%+)
- [ ] **TEST-04**: All 31 existing tests continue to pass throughout the refactor

### Docker

- [ ] **DOCK-01**: Dockerfile runs as non-root user
- [ ] **DOCK-02**: Docker health check configured
- [ ] **DOCK-03**: Build cache optimized (dependency layer cached separately from app code)
- [ ] **DOCK-04**: docker-compose.yml includes named volume for SQLite persistence

## v2 Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Pipeline Decomposition

- **PIPE-01**: SentinelService process_chunk decomposed into composable pipeline stage objects (DeduplicationStage, RateLimitStage, LLMDispatchStage)
- **PIPE-02**: Each pipeline stage is independently unit-testable

### Advanced Pagination

- **PAG-01**: Cursor/keyset pagination for high-volume endpoints

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| React SPA frontend | Deferred to ROADMAP Phase 1 — this milestone is backend-only refactor |
| Fix suggestions / knowledge base | Deferred to ROADMAP Phase 2 |
| SMTP email alerts | Deferred to ROADMAP Phase 3 |
| RAG / vector database | Deferred to ROADMAP Phase 4 |
| PostgreSQL migration | SQLite adequate for single-host; no user-visible benefit |
| FastAPI migration | Working framework stays per explicit constraint |
| GraphQL API | Fewer than 10 endpoints; REST serves React SPA adequately |
| Abstract base classes for 2 implementations | Over-engineering; use Protocol or concrete class |
| Settings split into multiple DB tables | DB schema stays flat; split in Python code only |
| Event sourcing for pipeline stages | Synchronous single-process loop; message broker overhead unjustified |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SRVC-01 | Phase 1 | Complete |
| SRVC-02 | Phase 1 | Complete |
| SRVC-03 | Phase 4 | Pending |
| SRVC-04 | Phase 4 | Pending |
| DI-01 | Phase 1 | Complete |
| DI-02 | Phase 1 | Complete |
| DI-03 | Phase 1 | Complete |
| CFG-01 | Phase 1 | Complete |
| CFG-02 | Phase 1 | Complete |
| CFG-03 | Phase 1 | Complete |
| REPO-01 | Phase 2 | Complete |
| REPO-02 | Phase 2 | Complete |
| REPO-03 | Phase 2 | Complete |
| MIG-01 | Phase 3 | Pending |
| MIG-02 | Phase 3 | Pending |
| MIG-03 | Phase 3 | Pending |
| MIG-04 | Phase 3 | Pending |
| APP-01 | Phase 4 | Pending |
| APP-02 | Phase 4 | Pending |
| APP-03 | Phase 4 | Pending |
| API-01 | Phase 5 | Pending |
| API-02 | Phase 5 | Pending |
| API-03 | Phase 5 | Pending |
| API-04 | Phase 5 | Pending |
| TEST-01 | Phase 5 | Pending |
| TEST-02 | Phase 5 | Pending |
| TEST-03 | Phase 5 | Pending |
| TEST-04 | All | Pending |
| DOCK-01 | Phase 5 | Pending |
| DOCK-02 | Phase 5 | Pending |
| DOCK-03 | Phase 5 | Pending |
| DOCK-04 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 32 total
- Mapped to phases: 32
- Unmapped: 0 ✓

---
*Requirements defined: 2026-04-04*
*Last updated: 2026-04-04 after initial definition*
