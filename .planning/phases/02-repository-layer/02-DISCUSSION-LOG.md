# Phase 2: Repository Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 02-repository-layer
**Areas discussed:** Session & transaction ownership, Repository injection, Singleton model handling, Query method granularity

---

## Session & Transaction Ownership

### Q1: Who should own db.session.commit() calls?

| Option | Description | Selected |
|--------|-------------|----------|
| Caller owns commit | Repos do add/delete/query but never commit. Services or routes call commit() after coordinating multiple repo operations. Standard Unit of Work pattern. | ✓ |
| Repo auto-commits each operation | Each repo method commits after its own work. Simpler per-method, but breaks atomicity for multi-step operations. | |
| Mixed — simple repos commit, complex don't | CRUD repos auto-commit; AnalysisEventRepository leaves commit to caller. Pragmatic but inconsistent. | |

**User's choice:** Caller owns commit (Recommended)
**Notes:** None

### Q2: Should repos receive session via constructor or import from extensions?

| Option | Description | Selected |
|--------|-------------|----------|
| Import from extensions | Repos import db from app.extensions — same pattern used everywhere in codebase. | ✓ |
| Constructor injection | Each repo takes session as constructor arg. More unit-testable but conflicts with "no mocking databases" constraint. | |
| Hybrid — default import, optional override | Default to db.session but accept optional session kwarg. Override would never be used. | |

**User's choice:** Import from extensions (Recommended)
**Notes:** None

---

## Repository Injection

### Q3: How should repositories be wired into ServiceContainer?

| Option | Description | Selected |
|--------|-------------|----------|
| Add repos as ServiceContainer attrs | Typed attributes on existing dataclass (container.event_repo, etc.). Follows Phase 1 pattern exactly. | ✓ |
| Repos instantiated inline where needed | Each service/route creates its own repo instance. Simpler but loses centralized wiring. | |
| Separate RepositoryContainer | Second container dataclass for repos. Clean separation but adds indirection. | |

**User's choice:** Add repos as ServiceContainer attrs (Recommended)
**Notes:** None

### Q4: Should services receive repos via constructor or access from container?

| Option | Description | Selected |
|--------|-------------|----------|
| Constructor injection | SentinelService.__init__(event_repo, ...) stores repos as instance attributes. Matches Phase 1 pattern. | ✓ |
| Container lookup at call time | Services receive full container and call self.container.event_repo. Hides dependencies. | |

**User's choice:** Constructor injection (Recommended)
**Notes:** None

---

## Singleton Model Handling

### Q5: Should singleton models get repository classes?

| Option | Description | Selected |
|--------|-------------|----------|
| SettingsRepo yes, others no | SettingsRepository wraps Settings.singleton(). SentinelState and SchemaVersion stay as-is (1-2 call sites each). | ✓ |
| All three get repos | Full consistency but SentinelState/SchemaVersion repos would be near-empty wrappers. | |
| None — singletons keep classmethods | Conflicts with REPO-02 which requires SettingsRepository. | |

**User's choice:** SettingsRepo yes, others no (Recommended)
**Notes:** None

---

## Query Method Granularity

### Q6: How specific should repository method names be?

| Option | Description | Selected |
|--------|-------------|----------|
| Domain-named methods | Methods named for caller intent: count_recent_calls(minutes), find_duplicate_chunk(hash, hours). Per CLAUDE.md guidance. | ✓ |
| Generic + specific hybrid | Base methods like get_by_id plus domain-specific ones. Adds generic layer project advises against. | |
| Query builder / filter pattern | Chainable filter API. Over-engineered for ~15 distinct queries. | |

**User's choice:** Domain-named methods (Recommended)
**Notes:** None

### Q7: Should as_dict() serialization live in repo or model?

| Option | Description | Selected |
|--------|-------------|----------|
| Keep as_dict() on models | Repos return ORM instances, routes call .as_dict(). Serialization is presentation concern. Phase 5 replaces with Pydantic. | ✓ |
| Move to repos as to_dict() | Repos return dicts. Couples repo to response shape. | |

**User's choice:** Keep as_dict() on models (Recommended)
**Notes:** None

---

## Claude's Discretion

- Exact method signatures and parameter naming on each repository class
- Internal helper methods within repositories
- Order of migration (which repo to extract first)
- Whether to extract app/__init__.py web route queries in Phase 2 or defer to Phase 4

## Deferred Ideas

None — discussion stayed within phase scope
