# Phase 2: Repository Layer - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Encapsulate all SQLAlchemy ORM queries into named repository classes under `app/repositories/`. After this phase, no service or route handler contains inline `.query.filter`, `.session.execute`, or `.session.query` calls. All 31 existing tests pass with no modifications to test logic.

</domain>

<decisions>
## Implementation Decisions

### Session & Transaction Ownership
- **D-01:** Repositories never call `db.session.commit()`. The caller (service or route handler) owns the commit — this preserves atomicity for multi-step flows like sentinel's dedup-check → LLM-call → save-event → alert-check pipeline.
- **D-02:** Repositories import `db` from `app.extensions` (not constructor-injected). This matches the existing codebase pattern used in all model and service files, and Flask-SQLAlchemy's request-scoped session handling makes this safe.

### Repository Injection & Wiring
- **D-03:** Repositories are added as typed attributes on the existing `ServiceContainer` dataclass from Phase 1 (`container.event_repo`, `container.settings_repo`, `container.prompt_repo`, `container.report_repo`, `container.exclusion_repo`).
- **D-04:** Services receive repositories via constructor injection — e.g., `SentinelService.__init__(event_repo, prompt_repo, ...)`. This extends the Phase 1 pattern where services already accept `llm_client`, `verdict_parser`, etc. as constructor args.
- **D-05:** Route handlers access repositories through the container (same as services): `container.event_repo.get_recent(limit=10)`.

### Singleton Model Handling
- **D-06:** `SettingsRepository` is created to wrap `Settings.singleton()` and the update/commit pattern used in `api/settings.py`. Required by REPO-02.
- **D-07:** `SentinelState` and `SchemaVersion` keep their existing `singleton()` classmethods — they are internal infrastructure with 1-2 call sites each. No repository needed.

### Query Method Granularity
- **D-08:** Each repository has domain-named methods matching current inline queries: `count_recent_calls(minutes)`, `find_duplicate_chunk(hash, hours)`, `get_recent_alerts(hours)`, etc. No generic base class with `get_by_id` / `find_all`.
- **D-09:** Repositories return ORM model instances, not dicts. `as_dict()` serialization stays on the model classes — it's a presentation concern. Phase 5 will replace `as_dict()` with Pydantic response models.

### Claude's Discretion
- Exact method signatures and parameter naming on each repository class
- Internal helper methods within repositories (e.g., shared date-range filtering)
- Order of migration (which repo to extract first)
- Whether to extract `app/__init__.py` web route queries in this phase or defer to Phase 4 (Blueprint extraction) — both are valid since REPO-03 says "no inline queries in services and routes"

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §Data Access — REPO-01, REPO-02, REPO-03 define the three acceptance criteria
- `.planning/ROADMAP.md` §Phase 2 — Goal, success criteria, dependency on Phase 1

### Query sites (all inline queries to encapsulate)
- `app/services/sentinel.py` — ~20 inline query/session calls (heaviest concentration: dedup, rate limiting, alert tracking)
- `app/services/briefing.py` — 3 calls (prompt lookup, event query for period, report save)
- `app/api/prompts.py` — 5 calls (list, get, update, restore)
- `app/api/reports.py` — 2 calls (list, get by ID)
- `app/api/exclusions.py` — 6 calls (list, create, delete with duplicate check)
- `app/api/settings.py` — 1 call (commit after update)
- `app/__init__.py` lines 130-270 — ~15 calls in web route handlers (events, exclusions, reports, prompts)
- `app/services/coordinator.py` — 1 session.commit call

### Models (what repos wrap)
- `app/models/events.py` — AnalysisEvent with 20+ columns, `as_dict()` serializer
- `app/models/exclusions.py` — ExclusionRule with unique container_pattern constraint
- `app/models/prompts.py` — PromptTemplate with versioned key-based lookup
- `app/models/reports.py` — DailyReport with date-ordered queries
- `app/models/settings.py` — Settings singleton pattern (25+ fields, `as_dict()`)

### Phase 1 integration points
- `app/container.py` — ServiceContainer dataclass to extend with repo attributes
- `app/__init__.py` lines 300-330 — Composition root in create_app() where repos will be instantiated and wired

### Research findings
- `.planning/research/ARCHITECTURE.md` — Target layered architecture, repository placement
- `.planning/research/PITFALLS.md` — Circular import warnings relevant to repository module structure

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/extensions.py`: `db` instance — all repos will import from here
- `app/container.py`: `ServiceContainer` dataclass — will be extended with repo attributes
- `app/time_utils.py`: `utcnow_naive` — already used in models, repos may need for date-range queries

### Established Patterns
- **Singleton pattern**: `Settings.singleton()` uses `db.session.get(cls, 1)` with auto-create. SettingsRepository will wrap this.
- **Service construction in create_app()**: All services instantiated in factory and stored in container. Repos follow same pattern.
- **Constructor injection**: Phase 1 established services receiving dependencies as constructor args. Repos extend this.
- **`as_dict()` on models**: All five models have `as_dict()` serializers. Repos return ORM instances; routes call `as_dict()`.

### Integration Points
- `create_app()` in `app/__init__.py` — where repos will be instantiated and added to ServiceContainer
- `SentinelService.__init__()` — will add `event_repo`, `prompt_repo` params alongside existing `llm_client`, `verdict_parser`
- `BriefingService.__init__()` — will add `event_repo`, `prompt_repo`, `report_repo` params
- `app/api/` route handlers — will access repos via `container.exclusion_repo`, `container.report_repo`, etc.

</code_context>

<specifics>
## Specific Ideas

- CLAUDE.md tech stack section explicitly says: "Don't use a generic repository base class with magical get_by_id, find_all — each repository has domain-specific query methods"
- The heaviest repo will be `AnalysisEventRepository` (~15 methods) covering sentinel's dedup check, rate limiting counts, recent events, alert tracking, and event creation
- `ExclusionRepository` and `ReportRepository` will be thin (3-4 methods each) — simple CRUD
- `PromptRepository` needs a `get_by_key(key)` method since prompts are looked up by `PromptTemplate.key`, not by ID

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-repository-layer*
*Context gathered: 2026-04-04*
