# Phase 1: Foundation - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Extract duplicate LLM invocation logic into a single LLMCallService, replace the string-keyed `app.extensions["services"]` dict with a typed ServiceContainer dataclass, and decompose the Settings god object (25+ fields) into domain-specific frozen config dataclasses. Zero schema changes, all 31 tests stay green.

</domain>

<decisions>
## Implementation Decisions

### LLM Service Design
- **D-01:** Create `app/services/llm_call.py` containing `LLMCallService` — a stateless service that accepts `llm_client` as a constructor argument and provides a single `call()` method encapsulating the transport-switching logic (API vs CLI), timeout/retry resolution, and the `complete()`/`chat_completion()` fallback dispatch.
- **D-02:** `SentinelService`, `BriefingService`, and `api/settings.py:test_llm_connection` all delegate to `LLMCallService.call()` — their private `_call_llm`, `_settings`, `_prompt` helper methods are deleted.
- **D-03:** The `temperature` parameter (briefing uses 0.2, sentinel omits it) becomes an optional kwarg on `LLMCallService.call()` with a default of `None` (passthrough to LLMClient behavior).

### ServiceContainer Shape
- **D-04:** Create `app/container.py` containing a mutable `@dataclass` named `ServiceContainer` with typed attributes: `llm_client`, `llm_call`, `verdict_parser`, `telegram_notifier`, `sentinel`, `briefing`, `coordinator`.
- **D-05:** `app.extensions["services"]` remains as the storage key, but now holds a `ServiceContainer` instance instead of a plain dict. Route handlers access via typed attributes: `container.sentinel` instead of `services["sentinel"]`.
- **D-06:** `ServiceContainer` implements `__getitem__` to delegate string-key lookups to `getattr` — this provides backwards compatibility for the 26 existing `extensions["services"]["key"]` references across routes and tests during the transition.
- **D-07:** All route handlers and tests are updated to use typed attribute access in this phase. The `__getitem__` shim remains as a safety net but all direct usages are migrated.

### Config Decomposition Strategy
- **D-08:** Create `app/config_objects.py` containing five frozen `@dataclass` classes: `LLMConfig`, `AlertConfig`, `CallReductionConfig`, `TelegramConfig`, `CLIConfig`. Each is constructed from a `Settings` ORM row via a `from_settings(settings)` classmethod.
- **D-09:** The `Settings` ORM model and DB schema are NOT modified — all 25+ columns stay in one table. The decomposition is at the Python code boundary only.
- **D-10:** Services accept domain-specific config objects as method parameters (e.g., `LLMCallService.call(config: LLMConfig, ...)`) instead of the raw `Settings` singleton. Config objects are constructed at the call site where `Settings.singleton()` is currently called.

### Claude's Discretion
- Exact field grouping within each config dataclass (which fields go in LLMConfig vs CLIConfig, etc.)
- Whether to add a `NightlyConfig` dataclass or leave nightly_hour/nightly_minute on the coordinator directly
- Internal method signatures on `LLMCallService` (parameter naming, return type)
- Order of migration within the phase (LLMCallService first vs container first)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### LLM invocation (duplication sites)
- `app/services/sentinel.py` lines 92–122 — `SentinelService._call_llm()`, the primary copy
- `app/services/briefing.py` lines 25–56 — `BriefingService._call_llm()`, near-identical with `temperature=0.2`
- `app/api/settings.py` lines 63–102 — `test_llm_connection()` inline LLM call with `retries=0`

### Service injection (all migration sites)
- `app/__init__.py` line 317 — `app.extensions["services"] = {...}` dict construction
- `app/api/` — 7 route files access services by string key (13 total references)
- `tests/` — 4 test files access/swap services by string key (13 total references)

### Settings model
- `app/models/settings.py` — Full 25+ field Settings singleton with `as_dict()` serializer

### Research findings
- `.planning/research/SUMMARY.md` — Phase ordering rationale and pitfall warnings
- `.planning/research/ARCHITECTURE.md` — Target layered architecture and component boundaries
- `.planning/research/PITFALLS.md` — Circular import warnings, test injection contract risks

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/services/llm_client.py` (LLMClient, 169 LOC): Already handles API transport (httpx) and CLI transport (CLIBackendRunner). `LLMCallService` wraps this — does NOT replace it.
- `app/services/cli_backends.py` (CLIBackendRunner): Single-concurrency lock for CLI subprocess execution. Stays as-is, used by LLMClient.
- `app/extensions.py`: SQLAlchemy `db` instance. Import pattern already avoids circular imports.

### Established Patterns
- **Singleton pattern**: `Settings.singleton()` and `SentinelState.singleton()` use `db.session.get(cls, 1)` with auto-create. Config dataclasses will be constructed from these singletons.
- **Service construction in create_app()**: All services are instantiated in `app/__init__.py` lines 300-330 and stored in the extensions dict. Container replaces this dict.
- **Blueprint registration**: API routes are already in blueprints. Web routes are in the factory (Phase 4 scope).

### Integration Points
- `create_app()` in `app/__init__.py` — where ServiceContainer will be constructed and stored
- `SentinelService.__init__()` — currently accepts `llm_client`, `verdict_parser`, `telegram_notifier`; will also accept `llm_call_service`
- `BriefingService.__init__()` — currently accepts `llm_client`; will accept `llm_call_service` instead
- All `current_app.extensions["services"]["key"]` call sites in `app/api/` — will use `container.key`

</code_context>

<specifics>
## Specific Ideas

- Research explicitly recommends LLMCallService extraction as highest-leverage first change (lowest blast radius, no schema impact, immediate deduplication of ~120 LOC)
- The `_call_llm` duplication between sentinel.py and briefing.py differs only in `temperature=0.2` for briefing — LLMCallService must preserve this via an optional parameter
- The `api/settings.py:test_llm_connection` variant is slightly different (hardcoded `retries=0`, `max_tokens=8`, `temperature=0.0`) — LLMCallService.call() should accept all of these as optional overrides

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-04-04*
