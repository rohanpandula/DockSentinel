# Phase 4: Service Decomposition and Blueprint - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning
**Source:** Recommendations accepted without deep-dive (all 4 gray areas locked to recommended options)

<domain>
## Phase Boundary

Extract alert-sending logic from `SentinelService` into a dedicated `AlertService` behind an `AlertStrategy` Protocol (with `TelegramAlertStrategy` as the first implementation), move all 8 web route handlers out of `app/__init__.py` into a single Blueprint in `app/web/routes.py`, and reduce `app/__init__.py` (currently 349 LOC) to under 100 LOC of pure app-factory wiring. All existing URL patterns and endpoint names are preserved; all 31 tests pass with no modifications to test logic.

</domain>

<decisions>
## Implementation Decisions

### AlertService Boundary (SRVC-03 + SRVC-04)
- **D-01:** Create `app/services/alerts.py` containing:
  - `AlertStrategy` — `typing.Protocol` with one method: `send(message: str, config: AlertConfig) -> tuple[bool, str | None]`. Message is the pre-formatted alert body; config carries transport-specific credentials (telegram_token, telegram_chat_id) and is the existing `AlertConfig` frozen dataclass from `app/config_objects.py`.
  - `TelegramAlertStrategy` — concrete class implementing the Protocol. Thin wrapper that reads `config.telegram_token` / `config.telegram_chat_id` and delegates HTTP to the existing `TelegramNotifier.send_message(token, chat_id, text)`. `TelegramNotifier` stays as the low-level HTTP client (keeps the transport layer isolated and easy to mock in tests).
  - `AlertService` — owns the full alert-gating pipeline extracted from `SentinelService._send_alert_if_allowed`: cooldown check, global rate-limit check, alert message formatting, and strategy dispatch. Constructor: `AlertService(strategy: AlertStrategy, event_repo: AnalysisEventRepository)`.
- **D-02:** `AlertService` exposes one public method: `maybe_send(event: AnalysisEvent, config: AlertConfig) -> tuple[bool, str | None]`. Returns `(sent, error_reason)` using the same tuple contract `SentinelService._send_alert_if_allowed` returns today — no change to downstream bookkeeping in `process_chunk`.
- **D-03:** `SentinelService.process_chunk` loses `_send_alert_if_allowed` entirely. For `verdict.classification == "critical"`, it calls `self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))` and assigns `event.alert_sent` / `event.alert_error` from the tuple. `telegram_notifier` is removed from `SentinelService.__init__` — it no longer has any transport dependency. Constructor gains `alert_service: AlertService`.
- **D-04:** Alert message formatting (the 4-line f-string currently in `_send_alert_if_allowed`) moves into a small `_format_message(event)` helper inside `AlertService`. Keeps formatting co-located with dispatch.
- **D-05:** `ServiceContainer` gains two new typed attributes: `alert_strategy: AlertStrategy` and `alert_service: AlertService`. `telegram_notifier` stays on the container (still used by `app/api/telegram.py` test endpoint, and it's the transport TelegramAlertStrategy wraps).

### Web Blueprint Layout (APP-01)
- **D-06:** Create `app/web/__init__.py` (empty package marker) and `app/web/routes.py` — a single Blueprint named `web` containing all 8 web route handlers currently in `_register_web_routes`. No per-domain split. Web handlers are short, share identical `container = current_app.extensions["services"]` access + redirect patterns, and per-domain splitting would be premature abstraction at this size (CLAUDE.md: "three similar lines > one premature helper").
- **D-07:** Inside the Blueprint, handlers access the ServiceContainer via `current_app.extensions["services"]` (same mechanism they use today — no new injection pattern needed, since Flask request context is available).
- **D-08:** `_register_web_routes(app)` in `app/__init__.py` is deleted. Blueprint registration moves into `_register_api_blueprints` (renamed to `_register_blueprints`) which imports `from app.web.routes import bp as web_bp` alongside the 8 API blueprints.

### Endpoint Name Preservation (APP-03)
- **D-09:** The web Blueprint is registered with `url_prefix=""` (no URL prefix — all current URLs like `/dashboard`, `/settings`, `/exclusions/delete/<int:rule_id>` stay byte-identical).
- **D-10:** Every `@bp.route(...)` decorator uses the `endpoint=` kwarg with the EXACT current endpoint name, so `url_for("dashboard")` in templates still resolves without a `web.` prefix. Required mappings:
  - `/` → endpoint=`"index"`
  - `/dashboard` → endpoint=`"dashboard"`
  - `/settings` → endpoint=`"settings_page"`
  - `/exclusions` → endpoint=`"exclusions_page"`
  - `/exclusions/delete/<int:rule_id>` → endpoint=`"exclusions_delete"`
  - `/insights` → endpoint=`"insights_page"`
  - `/reports` → endpoint=`"reports_page"`
  - `/reports/generate` → endpoint=`"reports_generate"`
  - `/prompts` → endpoint=`"prompt_studio_page"`
  - `/sentinel/toggle` → endpoint=`"sentinel_toggle_from_ui"`
  - `/sentinel/analyze` → endpoint=`"sentinel_analyze_from_ui"`
- **D-11:** Templates (`app/templates/*.html`) are NOT modified. Any test that calls `client.get("/dashboard")` or `url_for("dashboard")` continues to work unchanged.

### app/__init__.py Slimming Strategy (APP-02)
- **D-12:** Extract three things from `app/__init__.py` into new modules:
  - Web routes → `app/web/routes.py` (D-06)
  - `_seed_defaults()` (22 LOC) → `app/bootstrap.py` as `seed_defaults(db)` — called from the factory inside the app_context block.
  - Service/repository wiring block (lines ~300–340, ~40 LOC) → `app/composition.py` as `build_container(app) -> ServiceContainer` — instantiates all services, repos, strategy, AlertService, and returns a populated `ServiceContainer`.
- **D-13:** Keep inline in `app/__init__.py`:
  - `_ensure_sqlite_parent_dir()` (15 LOC) — tightly coupled to app.config, not worth extracting
  - `_register_blueprints()` (renamed from `_register_api_blueprints`) — imports stay in factory for clarity
  - `create_app()` — pure wiring: config load, db.init_app, TESTING gate for `db.create_all()`, `seed_defaults()`, `build_container()`, `_register_blueprints()`, coordinator start
- **D-14:** Target after extraction: `app/__init__.py` ≤ 90 LOC. Composition logic lives in `composition.py` (~50 LOC), seeding in `bootstrap.py` (~25 LOC), web routes in `app/web/routes.py` (~180 LOC — unchanged handler bodies).

### Claude's Discretion
- Exact ordering of operations within `build_container()` (as long as dependency order holds: repos → clients → services → coordinator)
- Internal helper method names inside `AlertService` (beyond `maybe_send` which is locked)
- Whether `app/bootstrap.py` takes `db` as a parameter or imports from `app.extensions` (consistent with repo pattern either way)
- Whether to introduce a `flush_only` param or related micro-optimizations in the route handlers — out of scope, keep bodies byte-identical when moving to Blueprint
- Exact test injection approach for `AlertService` (monkeypatch vs. ServiceContainer attribute swap) — either works since Phase 1 shim supports both

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/REQUIREMENTS.md` §Service Extraction — SRVC-03, SRVC-04 (AlertService + AlertStrategy + TelegramAlertStrategy)
- `.planning/REQUIREMENTS.md` §App Structure — APP-01, APP-02, APP-03 (Blueprint extraction, <100 LOC factory, endpoint name preservation)
- `.planning/ROADMAP.md` §Phase 4 — Goal, success criteria, dependency on Phase 3

### Code to extract from
- `app/__init__.py` lines 38–53 — `_ensure_sqlite_parent_dir` (keep inline)
- `app/__init__.py` lines 56–78 — `_seed_defaults` (move to `app/bootstrap.py`)
- `app/__init__.py` lines 82–99 — `_register_api_blueprints` (rename to `_register_blueprints`, add web_bp import)
- `app/__init__.py` lines 102–277 — `_register_web_routes` (ALL 8 handlers move to `app/web/routes.py`)
- `app/__init__.py` lines 280–349 — `create_app` (service wiring at lines 300–340 moves to `app/composition.py`)
- `app/services/sentinel.py` lines 265–289 — `_send_alert_if_allowed` (move to AlertService, with modifications per D-02/D-04)
- `app/services/sentinel.py` lines 255–258 — alert trigger in `process_chunk` (becomes `self.alert_service.maybe_send(...)`)
- `app/services/sentinel.py` lines 23–39 — `SentinelService.__init__` signature (remove `telegram_notifier`, add `alert_service`)

### Existing assets to reuse (do NOT rewrite)
- `app/services/telegram.py` — `TelegramNotifier.send_message(token, chat_id, text)`. TelegramAlertStrategy wraps this; do not rename or inline it.
- `app/config_objects.py` lines 39–55 — `AlertConfig` frozen dataclass with `from_settings()` classmethod. AlertStrategy.send and AlertService.maybe_send both consume this.
- `app/container.py` — `ServiceContainer` dataclass (extend with `alert_strategy`, `alert_service` attributes)
- `app/repositories/analysis_events.py` — `find_alert_duplicate(hash, since)` and `count_recent_alerts(since)` methods used by cooldown/rate-limit gating (AlertService uses these)

### Templates (endpoint consumers — do NOT modify)
- `app/templates/base.html` — calls `url_for('dashboard')`, `url_for('settings_page')`, `url_for('exclusions_page')`, `url_for('insights_page')`, `url_for('reports_page')`, `url_for('prompt_studio_page')`
- `app/templates/dashboard.html` — calls `url_for('sentinel_toggle_from_ui')`, `url_for('sentinel_analyze_from_ui')`
- `app/templates/exclusions.html`, `reports.html`, `prompt_studio.html` — additional `url_for()` references (verify during planning)

### Tests (must stay green unmodified)
- `tests/test_ui_routes.py` — exercises every web endpoint via `client.get("/dashboard")` etc. Highest signal for APP-03 regression.
- `tests/test_sentinel_pipeline.py` — exercises the critical-alert path; asserts `event.alert_sent` + `event.alert_error`. Validates AlertService tuple contract.
- `tests/test_api.py` — exercises `/api/telegram` endpoints. Validates `telegram_notifier` still accessible on container.

### Prior phase context (decisions carried forward)
- `.planning/phases/01-foundation/01-CONTEXT.md` — ServiceContainer shape + `__getitem__` shim + AlertConfig existence
- `.planning/phases/02-repository-layer/02-CONTEXT.md` — Repositories don't commit, callers do (D-01 Phase 2) — AlertService inherits this rule
- `.planning/phases/03-alembic-migration-infrastructure/03-CONTEXT.md` — TESTING-gate pattern for `db.create_all()`

### CLAUDE.md guidance
- `./CLAUDE.md` §Alert Strategy Pattern — "Standard library only" — use `typing.Protocol`, not `abc.ABC`
- `./CLAUDE.md` §What NOT to Add — "Abstract base classes for 2 implementations — over-engineering; use Protocol"
- User global — "three similar lines > one premature helper" → single web Blueprint, not per-domain split

### External skills consulted (informing recommendations)
- `alirezarezvani/claude-skills` — `engineering-team/senior-backend/SKILL.md` (per-resource blueprint pattern, minimal factory target) and `engineering-team/senior-architect/SKILL.md` (service extraction criteria)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `app/config_objects.py::AlertConfig` — already has all fields AlertService/AlertStrategy need (cooldown_minutes, rate_limit_count, rate_limit_window_seconds, telegram_token, telegram_chat_id). No new config work.
- `app/services/telegram.py::TelegramNotifier` — correct low-level HTTP client; TelegramAlertStrategy delegates to this.
- `app/repositories/analysis_events.py` — `find_alert_duplicate` and `count_recent_alerts` already exist (Phase 2). AlertService calls these directly.
- `app/container.py::ServiceContainer` — extend with two attributes; `__getitem__` shim auto-handles string-key lookups during any test transition.
- `app/api/*.py` — 8 blueprint files demonstrate the exact Blueprint + endpoint pattern to mirror for `app/web/routes.py`.

### Established Patterns
- **Blueprint per module**: API routes already use `bp = Blueprint(...)` + `@bp.route` + registration in `_register_api_blueprints`. Web Blueprint follows the same pattern.
- **Container access in handlers**: Both API and web handlers access `current_app.extensions["services"]` (or equivalently `app.extensions["services"]`) — no change needed.
- **Constructor injection for services**: Phase 1/2 established services accept typed deps in `__init__`. AlertService follows this (`strategy`, `event_repo`).
- **Frozen config dataclasses**: Phase 1 established services accept domain configs via method params. AlertService.maybe_send takes `AlertConfig` per this precedent.
- **Tuple return contract for alert dispatch**: `(bool, str | None)` tuple is already the telegram_notifier + `_send_alert_if_allowed` shape. Preserve it end-to-end.

### Integration Points
- `app/composition.py::build_container()` (new) — instantiates `TelegramAlertStrategy(telegram_notifier)` → `AlertService(strategy=..., event_repo=...)` → passes `alert_service` into `SentinelService(...)`.
- `SentinelService.__init__` — drops `telegram_notifier`, adds `alert_service`. Existing tests that inject `telegram_notifier` swap to injecting `alert_service` (or a fake strategy via `AlertService(FakeStrategy(), event_repo)`).
- `app/__init__.py::_register_blueprints()` — imports web_bp alongside 8 API bps; registers all together.
- `app/web/routes.py` — web Blueprint with `url_prefix=""` and explicit `endpoint=` kwargs on every route decorator.

</code_context>

<specifics>
## Specific Ideas

- The `classification == "critical"` trigger in `SentinelService.process_chunk` must stay in Sentinel — AlertService's `maybe_send` receives the event only when classification is critical. Do NOT move the classification check into AlertService (keeps AlertService transport-agnostic and testable with any AnalysisEvent).
- `TelegramNotifier.send_message` returns `tuple[bool, str | None]` — this matches the Protocol contract exactly. TelegramAlertStrategy becomes trivially thin (~8 LOC).
- Web Blueprint endpoint names MUST match the current function names 1:1 — the factory today derives endpoint names from function names (`def dashboard():` → endpoint `"dashboard"`). Blueprint prefixes would break this unless `endpoint=` is set explicitly on every decorator.
- `app/__init__.py` currently imports ~12 service/repo symbols for the wiring block. After D-12, those imports move with the wiring to `app/composition.py`, shrinking the factory's import block significantly.
- User explicitly accepted all 4 recommendations without follow-up questions ("go with recommendations"). No follow-up gray areas should be introduced during planning — scope is locked.

</specifics>

<deferred>
## Deferred Ideas

- Slack / Discord / email alert strategies — SRVC-03/04 covers Telegram only; additional strategies are in ROADMAP Phase 3 (Notification Center). The Protocol shape here is deliberately designed to accept them later without AlertService changes.
- SentinelService pipeline decomposition into `DeduplicationStage` / `RateLimitStage` / `LLMDispatchStage` — tracked as PIPE-01/PIPE-02 in v2 requirements; explicitly out of Phase 4 scope.
- `AlertService.maybe_send` observability / structured logging — Phase 5 (API Quality) is the natural home; this phase preserves current logging fidelity only.

</deferred>

---

*Phase: 04-service-decomposition-and-blueprint*
*Context gathered: 2026-04-14 — recommendations-only mode*
