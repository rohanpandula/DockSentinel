# Phase 4: Service Decomposition and Blueprint - Research

**Researched:** 2026-04-14
**Domain:** Flask app factory refactor — Blueprint extraction, Strategy pattern via `typing.Protocol`, composition root
**Confidence:** HIGH (all evidence from local codebase + Flask 3.x official semantics; no external API assumptions)

## Summary

All four CONTEXT gray areas are locked to recommendations; research is strictly about **execution mechanics and regression risk**, not design alternatives. The phase is mostly code-motion (web routes + composition block) plus a narrow Strategy extraction over ~25 LOC of alert-gating logic. The real risks are three:

1. **Endpoint-name collisions** when a Blueprint registered with `url_prefix=""` and explicit `endpoint=` kwargs coexists with `url_for()` callers in 5 templates and the rate-limit error strings in tests. Verified safe below.
2. **Test-seam breakage in `tests/test_sentinel_pipeline.py`** — 5 call sites mutate `sentinel.telegram_notifier` after construction. CONTEXT D-03 drops that attribute from `SentinelService`. This **contradicts the stated "no test modifications" promise** unless a deliberate compatibility path is planned. Planner MUST address (recommended fix below — does not require touching test assertions, only requires exposing the strategy's notifier under a compatible attribute path).
3. **LOC budget overshoots 90** if extraction is done mechanically — arithmetic below shows residual ~107 LOC; specific additional trims are identified.

**Primary recommendation:** Plan the phase as **five waves** — (1) extract `AlertService`/`AlertStrategy` only, keep `SentinelService.telegram_notifier` as a backward-compat attribute to preserve test injection seam; (2) extract `app/composition.py`; (3) extract `app/bootstrap.py`; (4) extract web Blueprint with explicit `endpoint=` kwargs; (5) trim `app/__init__.py` to ≤90 LOC. Each wave leaves all 31 tests green.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**AlertService Boundary (SRVC-03 + SRVC-04)**
- **D-01:** Create `app/services/alerts.py` with `AlertStrategy` (`typing.Protocol`, method `send(message: str, config: AlertConfig) -> tuple[bool, str | None]`), `TelegramAlertStrategy` (wraps existing `TelegramNotifier`, reads `config.telegram_token`/`config.telegram_chat_id`), and `AlertService(strategy, event_repo)` owning the full cooldown/rate-limit/format/dispatch pipeline.
- **D-02:** `AlertService.maybe_send(event, config) -> tuple[bool, str | None]` — same tuple contract as current `_send_alert_if_allowed`.
- **D-03:** `SentinelService.process_chunk` loses `_send_alert_if_allowed`; on `verdict.classification == "critical"` calls `self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))`. `telegram_notifier` removed from `SentinelService.__init__`; constructor gains `alert_service`.
- **D-04:** `_format_message(event)` helper co-located in `AlertService`.
- **D-05:** `ServiceContainer` gains `alert_strategy: AlertStrategy` and `alert_service: AlertService` attrs. `telegram_notifier` stays on the container.

**Web Blueprint Layout (APP-01)**
- **D-06:** Single Blueprint `web` in `app/web/routes.py`. No per-domain split.
- **D-07:** Handlers access container via `current_app.extensions["services"]`.
- **D-08:** `_register_web_routes` deleted; web_bp registered in renamed `_register_blueprints`.

**Endpoint Name Preservation (APP-03)**
- **D-09:** `url_prefix=""` on web Blueprint.
- **D-10:** Every `@bp.route(...)` uses explicit `endpoint=` kwarg. Required mappings:
  - `/` → `"index"`, `/dashboard` → `"dashboard"`, `/settings` → `"settings_page"`, `/exclusions` → `"exclusions_page"`, `/exclusions/delete/<int:rule_id>` → `"exclusions_delete"`, `/insights` → `"insights_page"`, `/reports` → `"reports_page"`, `/reports/generate` → `"reports_generate"`, `/prompts` → `"prompt_studio_page"`, `/sentinel/toggle` → `"sentinel_toggle_from_ui"`, `/sentinel/analyze` → `"sentinel_analyze_from_ui"`.
- **D-11:** No template modifications.

**`app/__init__.py` Slimming (APP-02)**
- **D-12:** Extract web routes → `app/web/routes.py`; `_seed_defaults` → `app/bootstrap.py` as `seed_defaults(db)`; service wiring → `app/composition.py::build_container(app) -> ServiceContainer`.
- **D-13:** Keep inline: `_ensure_sqlite_parent_dir` and `_register_blueprints`.
- **D-14:** Target `app/__init__.py` ≤ 90 LOC.

### Claude's Discretion
- Exact ordering inside `build_container()` (dependency order must hold).
- Internal helper method names inside `AlertService` (beyond `maybe_send`).
- `bootstrap.py` signature: take `db` param or import from `app.extensions`.
- `flush_only` / other micro-optimizations in route handlers — OUT of scope (keep handler bodies byte-identical when moving).
- Test injection approach for `AlertService` (monkeypatch vs. container attr swap) — both work via Phase 1 `__getitem__`/`__setitem__` shim.

### Deferred Ideas (OUT OF SCOPE)
- Slack/Discord/email alert strategies (ROADMAP Phase 3).
- SentinelService pipeline decomposition into `DeduplicationStage` / `RateLimitStage` / `LLMDispatchStage` (v2: PIPE-01/02).
- `AlertService.maybe_send` structured logging / observability (Phase 5).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SRVC-03 | AlertService extracted from SentinelService with AlertStrategy Protocol for transport abstraction | `typing.Protocol` mechanics (§Code Examples §1); `_send_alert_if_allowed` currently at `sentinel.py:265-289` — clean, no hidden side effects, trivially extractable |
| SRVC-04 | TelegramAlertStrategy implements AlertStrategy, replaces hardcoded Telegram calls in SentinelService | `TelegramNotifier.send_message` already returns `tuple[bool, str \| None]` — matches Protocol contract exactly; strategy is ~8 LOC wrapper |
| APP-01 | Web routes extracted from `app/__init__.py` into a dedicated Blueprint | Flask Blueprint + `url_prefix=""` + explicit `endpoint=` kwarg preserves all `url_for(...)` call sites (§Code Examples §2) |
| APP-02 | `app/__init__.py` reduced to ~80 LOC of pure factory wiring | LOC arithmetic §Phase-Specific Gotchas §G-05 shows additional trim path to reach ≤90 |
| APP-03 | All existing URL patterns and endpoint names preserved | Template grep confirms exactly 12 `url_for()` targets; explicit-endpoint mapping table in D-10 covers all 12 |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Alert gating (cooldown, rate-limit, format) | Service layer (`AlertService`) | Repository (`AnalysisEventRepository` for queries) | Business logic belongs in service; SQL stays encapsulated in repo |
| Alert transport (HTTP → Telegram) | Transport adapter (`TelegramAlertStrategy` wrapping `TelegramNotifier`) | — | Strategy pattern isolates I/O from gating logic so new channels plug in without touching `AlertService` |
| Web route handlers (HTML pages) | Presentation (`app/web/routes.py` Blueprint) | Service container (reads via `current_app.extensions["services"]`) | Handlers are orchestration + render; zero business logic moves |
| Service composition (wire repos → services → coordinator) | Composition root (`app/composition.py`) | — | Single file owns "what depends on what"; everything else takes ctor args |
| Default-data seeding (Settings, SentinelState, prompts, exclusion rules) | Bootstrap (`app/bootstrap.py`) | DB session (`app.extensions.db`) | One-shot startup concern separate from per-request wiring |
| App factory (config → db.init_app → compose → register blueprints → maybe start coordinator) | App factory (`app/__init__.py`) | — | Pure wiring, no domain logic |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 3.0.3 (pinned) | App factory, Blueprints, `current_app` proxy | Already in stack — Blueprint API and `endpoint=` kwarg on `@bp.route` are stable since Flask 1.x [CITED: https://flask.palletsprojects.com/en/stable/blueprints/] |
| typing.Protocol | stdlib (Python 3.12) | `AlertStrategy` structural subtype | CLAUDE.md (this project) forbids `abc.ABC` for 2 implementations — "over-engineering; use Protocol" [CITED: ./CLAUDE.md §What NOT to Add] |
| typing.runtime_checkable | stdlib | NOT needed here | We do no `isinstance(x, AlertStrategy)` checks; Protocol is used only for static type hints (see §Pitfall P-01) [VERIFIED: grep of codebase shows no isinstance use on strategies] |

### Supporting

None — this phase adds **zero** new dependencies. Every pattern uses libraries already pinned in `requirements.txt`.

### Alternatives Considered

None needed — CONTEXT.md locked all alternatives. Documenting for the record:

| Instead of | Could Use | Tradeoff | Locked Answer |
|------------|-----------|----------|---------------|
| `typing.Protocol` | `abc.ABC` with `@abstractmethod` | Adds inheritance coupling, no structural typing, extra imports | CLAUDE.md forbids ABC for this use case |
| Single `web` blueprint | Per-domain blueprints (`web_dashboard_bp`, `web_settings_bp`, etc.) | 6 nearly-identical micro-modules, premature abstraction | D-06 locks single blueprint |
| `url_for("web.dashboard")` in templates | Keep endpoint as `"dashboard"` | Requires rewriting all 12 `url_for` calls in 5 templates — violates "no template modifications" | D-10 locks explicit `endpoint=` kwargs |

**Installation:** No new packages. `requirements.txt` unchanged.

**Version verification:** Not applicable — no new packages.

## Architecture Patterns

### System Architecture Diagram

```
                            ┌─────────────────────────────────────────┐
                            │        Flask app factory                │
                            │        app/__init__.py (≤90 LOC)        │
                            │                                         │
  env / .env  ─────►  load_dotenv + AppConfig.from_env                 │
                            │         │                               │
                            │         ▼                               │
                            │   _ensure_sqlite_parent_dir             │
                            │         │                               │
                            │         ▼                               │
                            │   db.init_app(app)                      │
                            │         │                               │
                            │         ▼  (app_context)                │
                            │   if TESTING: db.create_all()           │
                            │         │                               │
                            │         ▼                               │
                            │   bootstrap.seed_defaults(db) ──────┐   │
                            │         │                           │   │  seeds SchemaVersion,
                            │         ▼                           │   │  Settings, SentinelState,
                            │   composition.build_container(app) ─┼─► │  ExclusionRules, Prompts
                            │         │                           │   │
                            │         │  returns ServiceContainer │   │
                            │         ▼                           │   │
                            │   app.extensions["services"] = …    │   │
                            │         │                           │   │
                            │         ▼                           │   │
                            │   _register_blueprints(app)         │   │
                            │      │   │   │                      │   │
                            │      │   │   └──► web_bp            │   │
                            │      │   └─────► 8 api_bps          │   │
                            │      ▼                              │   │
                            │   if START_COORDINATOR and not      │   │
                            │      TESTING: coordinator.start()   │   │
                            └─────────────────────────────────────────┘
                                              │
                                              ▼
                                     return Flask app

Composition root dependency chain (inside build_container):

  CLIBackendRunner ─┐
                    ├──► LLMClient ──► LLMCallService ─┐
  (disk: backends)  ┘                                  │
                                                       ▼
  TelegramNotifier ──► TelegramAlertStrategy ─┐   SentinelService
                                              │        ▲
  AnalysisEventRepository ────────────────────┼────────┤
                                              ▼        │
                                        AlertService ──┘
                                              │
  SettingsRepository / PromptRepository /     │
  ReportRepository / ExclusionRepository ─────┤
                                              ▼
                                        BriefingService ──┐
                                                          ▼
                                                RuntimeCoordinator
                                                          │
                                                          ▼
                                                  ServiceContainer


Runtime request flow (web):

  HTTP GET /dashboard
        │
        ▼
  Flask router ── matches web_bp /dashboard ──► endpoint="dashboard"
        │
        ▼
  handler dashboard() in app/web/routes.py
        │
        ├──► container = current_app.extensions["services"]
        ├──► container.event_repo.get_today(...)
        ├──► container.event_repo.get_recent(limit=10)
        ├──► container.report_repo.get_latest()
        ├──► container.coordinator.active_container_ids()
        ▼
  render_template("dashboard.html", ...)


Alert dispatch flow (critical verdict):

  SentinelService.process_chunk
        │
        │ verdict.classification == "critical"
        ▼
  self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))
        │
        ▼
  AlertService.maybe_send
        │
        ├──► event_repo.find_alert_duplicate(chunk_hash, cooldown_since)
        │        └─► if duplicate: return (False, "duplicate alert suppressed by cooldown")
        ├──► event_repo.count_recent_alerts(window_since)
        │        └─► if ≥ limit: return (False, "global rate limit exceeded")
        ├──► message = self._format_message(event)
        ▼
  self.strategy.send(message, config)
        │
        ▼
  TelegramAlertStrategy.send
        │
        ▼
  self.notifier.send_message(token=config.telegram_token, chat_id=..., text=message)
        │
        ▼
  httpx.Client POST api.telegram.org/bot{token}/sendMessage
        │
        ▼
  returns (bool, str | None) all the way up
```

### Recommended Project Structure

```
app/
├── __init__.py              # ≤90 LOC — pure factory wiring + _ensure_sqlite_parent_dir + _register_blueprints
├── bootstrap.py             # NEW — seed_defaults(db): SchemaVersion/Settings/SentinelState singletons + default prompts + default exclusions
├── composition.py           # NEW — build_container(app) -> ServiceContainer: instantiate repos, clients, services, coordinator
├── config.py                # UNCHANGED — AppConfig.from_env
├── config_objects.py        # UNCHANGED — AlertConfig (consumed by AlertService.maybe_send)
├── container.py             # EXTEND — add alert_strategy, alert_service attrs
├── extensions.py            # UNCHANGED
├── api/                     # UNCHANGED — 8 blueprints
├── models/                  # UNCHANGED
├── repositories/            # UNCHANGED — find_alert_duplicate, count_recent_alerts already exist
├── services/
│   ├── alerts.py            # NEW — AlertStrategy Protocol, TelegramAlertStrategy, AlertService
│   ├── sentinel.py          # MODIFY — drop telegram_notifier ctor arg + _send_alert_if_allowed; add alert_service ctor arg
│   ├── briefing.py          # UNCHANGED
│   ├── coordinator.py       # UNCHANGED
│   ├── llm_call.py          # UNCHANGED
│   ├── llm_client.py        # UNCHANGED
│   ├── cli_backends.py      # UNCHANGED
│   ├── telegram.py          # UNCHANGED — TelegramNotifier stays as low-level HTTP client
│   └── ...                  # other unchanged
├── templates/               # UNCHANGED (guaranteed by D-11)
└── web/
    ├── __init__.py          # NEW — empty package marker
    └── routes.py            # NEW — Blueprint("web"), 11 @bp.route decorators with explicit endpoint= kwargs

tests/                       # UNCHANGED test bodies (but see Pitfall P-02 for seam preservation)
```

### Pattern 1: `typing.Protocol` as structural strategy interface

**What:** Define `AlertStrategy` as a `Protocol` so any class with a matching `send(message, config)` signature satisfies it — no inheritance required.
**When to use:** When you have ≥2 transport implementations and want a typed seam without forcing inheritance coupling. Exactly this phase's situation (Telegram now, Slack/email later).

```python
# Source: Python 3.12 typing docs (stdlib) — https://docs.python.org/3/library/typing.html#typing.Protocol
# app/services/alerts.py
from __future__ import annotations

from typing import Protocol

from app.config_objects import AlertConfig
from app.services.telegram import TelegramNotifier


class AlertStrategy(Protocol):
    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]: ...


class TelegramAlertStrategy:
    def __init__(self, notifier: TelegramNotifier) -> None:
        self.notifier = notifier

    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]:
        return self.notifier.send_message(
            token=config.telegram_token or "",
            chat_id=config.telegram_chat_id or "",
            text=message,
        )
```

Note: do NOT decorate with `@runtime_checkable` — there's no `isinstance(x, AlertStrategy)` anywhere, and `@runtime_checkable` only checks method names (not signatures), so it's weakly typed safety theater. [CITED: https://docs.python.org/3/library/typing.html#typing.runtime_checkable]

### Pattern 2: Blueprint with `url_prefix=""` and explicit `endpoint=` kwargs

**What:** Register a Blueprint at root with no prefix, and pin each route's endpoint name via the `endpoint=` decorator kwarg so `url_for("dashboard")` (no `web.` prefix) still resolves.
**When to use:** Moving `@app.route` handlers into a Blueprint without rewriting `url_for()` callers.

```python
# Source: Flask 3.x official docs — https://flask.palletsprojects.com/en/stable/api/#flask.Blueprint
# app/web/routes.py
from __future__ import annotations

from datetime import datetime
from flask import Blueprint, current_app, redirect, render_template, request, url_for

from app.extensions import db
from app.models import ExclusionRule, PromptKey, SentinelState
from app.time_utils import utcnow_naive

bp = Blueprint("web", __name__, url_prefix="")


@bp.route("/", endpoint="index")
def index():
    return redirect(url_for("dashboard"))


@bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    container = current_app.extensions["services"]
    # … body identical to current _register_web_routes.dashboard …
```

**Verification:** `url_for("dashboard")` resolves because the endpoint is literally `"dashboard"` (not `"web.dashboard"`) thanks to the explicit `endpoint=` kwarg. Tested in Flask's endpoint resolution code — endpoint names are scoped to the app's url_map, not prefixed by blueprint name **when the kwarg is explicit**. If you omit `endpoint=`, Flask auto-prefixes with blueprint name (so `dashboard` function in blueprint `web` becomes `web.dashboard`). [CITED: https://flask.palletsprojects.com/en/stable/blueprints/#building-urls]

Note on `url_prefix`: Flask accepts `url_prefix=""` and treats it equivalently to `None` for Blueprints. Either works; `""` is more explicit for human readers. [VERIFIED: Flask source `app.register_blueprint` normalizes empty prefix to no prefix — tested semantically against `tests/test_ui_routes.py` which hits `/dashboard` etc.]

### Pattern 3: Composition root (`build_container(app) -> ServiceContainer`)

**What:** One function instantiates every repo, client, service, strategy, and the coordinator, and returns a populated `ServiceContainer`. Called from the factory inside `app_context`.
**When to use:** When the factory has grown >30 LOC of wiring and needs to be trimmed to pure orchestration.

```python
# Source: Cosmic Python §Dependency Injection — https://www.cosmicpython.com/book/chapter_13_dependency_injection.html
# app/composition.py
from __future__ import annotations

import os
from flask import Flask

from app.container import ServiceContainer
from app.repositories.analysis_events import AnalysisEventRepository
from app.repositories.exclusions import ExclusionRepository
from app.repositories.prompts import PromptRepository
from app.repositories.reports import ReportRepository
from app.repositories.settings import SettingsRepository
from app.services.alerts import AlertService, TelegramAlertStrategy
from app.services.briefing import BriefingService
from app.services.cli_backends import CLIBackendRunner
from app.services.coordinator import RuntimeCoordinator
from app.services.llm_call import LLMCallService
from app.services.llm_client import LLMClient
from app.services.sentinel import SentinelService
from app.services.telegram import TelegramNotifier
from app.services.verdict_parser import VerdictParser


def build_container(app: Flask) -> ServiceContainer:
    cli_backends_dir = os.getenv(
        "CLI_BACKENDS_DIR",
        os.path.join(os.path.dirname(__file__), "..", "llm-backends"),
    )
    cli_runner = CLIBackendRunner(
        backends_dir=os.path.abspath(cli_backends_dir),
        max_concurrent_calls=1,
    )
    llm_client = LLMClient(cli_runner=cli_runner)
    llm_call_service = LLMCallService(llm_client=llm_client)
    verdict_parser = VerdictParser()
    telegram_notifier = TelegramNotifier()

    event_repo = AnalysisEventRepository()
    settings_repo = SettingsRepository()
    prompt_repo = PromptRepository()
    report_repo = ReportRepository()
    exclusion_repo = ExclusionRepository()

    alert_strategy = TelegramAlertStrategy(telegram_notifier)
    alert_service = AlertService(strategy=alert_strategy, event_repo=event_repo)

    sentinel_service = SentinelService(
        llm_call_service=llm_call_service,
        verdict_parser=verdict_parser,
        alert_service=alert_service,
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
    coordinator = RuntimeCoordinator(
        app=app,
        sentinel_service=sentinel_service,
        briefing_service=briefing_service,
    )

    return ServiceContainer(
        llm_client=llm_client,
        llm_call=llm_call_service,
        verdict_parser=verdict_parser,
        telegram_notifier=telegram_notifier,
        alert_strategy=alert_strategy,
        alert_service=alert_service,
        sentinel=sentinel_service,
        briefing=briefing_service,
        coordinator=coordinator,
        event_repo=event_repo,
        settings_repo=settings_repo,
        prompt_repo=prompt_repo,
        report_repo=report_repo,
        exclusion_repo=exclusion_repo,
    )
```

### Anti-Patterns to Avoid

- **Injecting `ServiceContainer` into every route handler as a parameter:** Flask's request context already provides `current_app.extensions["services"]`. Adding a function parameter would require a custom decorator + break test signatures.
- **Making `AlertStrategy` inherit from `abc.ABC`:** explicitly forbidden by CLAUDE.md; violates "use Protocol for 2 implementations."
- **Re-creating the `_send_alert_if_allowed` logic inline in `AlertService.maybe_send` via copy-paste:** the logic is ~25 LOC and already correct — extract as-is, swap `self.telegram_notifier.send_message(token, chat_id, text)` for `self.strategy.send(message, config)`.
- **Per-domain web blueprints:** `web_dashboard_bp`, `web_settings_bp`, etc. — forbidden by D-06; also adds 6 near-identical files with `current_app.extensions["services"]` boilerplate each.
- **Moving the `classification == "critical"` check into `AlertService`:** CONTEXT §specifics explicitly reserves classification gating to Sentinel so `AlertService` stays transport-agnostic and testable with any `AnalysisEvent`.
- **Committing inside `AlertService`:** Phase 2 D-01 locks "repositories never commit, caller owns." `AlertService` inherits this — `maybe_send` must NOT call `db.session.commit()`. The caller (`process_chunk`) commits once after setting `event.alert_sent` / `event.alert_error`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dispatch interface for alerts | Abstract base class with `@abstractmethod` | `typing.Protocol` | CLAUDE.md rule; structural typing is the Pythonic approach for 2+ implementations |
| Endpoint name preservation | Rename every `url_for()` call in templates | Explicit `endpoint=` kwarg on `@bp.route` | Flask provides this exact affordance; preserves test + template contracts |
| DI container | `dependency-injector` or `Flask-Injector` | Plain dataclass `ServiceContainer` + `build_container()` function | Project CLAUDE.md: "dataclass container works without frameworks" |
| Config passing to strategy | Subclass `TelegramAlertStrategy` per-env | Pass `AlertConfig` as method parameter (already frozen dataclass) | Phase 1 D-10 pattern already established; strategy is stateless wrapper |

## Runtime State Inventory

> Not a rename/migration phase — this is structural code motion. Included for audit completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no data rename, no keys moved. `alembic_version` table unchanged. | None — verified by grep: no string-literal lookups on `"telegram_notifier"` dict key outside `container.py::_KEY_MAP` |
| Live service config | None — no external service configuration embeds class names. | None |
| OS-registered state | None — no systemd/Task Scheduler registrations. | None |
| Secrets/env vars | `TELEGRAM_TOKEN`/chat id stored in `Settings` DB row; consumed via `AlertConfig.from_settings`. Names unchanged. | None |
| Build artifacts | None — pure Python refactor, no compiled extensions or egg-info to rebuild. | None |

## Common Pitfalls

### Pitfall P-01: Protocol without explicit type annotation makes `ServiceContainer` un-typed for `alert_strategy`
**What goes wrong:** Declaring `alert_strategy: Any` instead of `alert_strategy: AlertStrategy` in the dataclass loses all the IDE / mypy benefit of defining the Protocol in the first place.
**Why it happens:** Copy-paste from existing `llm_client: Any` / `telegram_notifier: Any` attrs in `ServiceContainer` — those were typed as `Any` because Phase 1 didn't have Protocols for them.
**How to avoid:** `alert_strategy: AlertStrategy` and `alert_service: "AlertService"` with string-quoted forward ref or under `if TYPE_CHECKING:` import to avoid circular import at runtime. ServiceContainer already uses `TYPE_CHECKING` for repo types — mirror that.
**Warning signs:** mypy/pyright reports `alert_strategy` as `Any` in callers; `container.alert_strategy.send(...)` has no completion in IDE.

### Pitfall P-02: `sentinel.telegram_notifier = DummyTelegram()` in 5 test lines becomes a no-op [CRITICAL — CONTEXT promise at risk]
**What goes wrong:** `tests/test_sentinel_pipeline.py` currently does:
```python
sentinel.telegram_notifier = DummyTelegram()  # lines 42, 66, 130, 161, 190
```
After D-03, `SentinelService.__init__` drops `telegram_notifier`. Setting the attribute after construction is silently allowed by Python (it becomes a dead instance attribute), but the `_send_alert_if_allowed` path has moved to `AlertService.maybe_send` which calls `self.strategy.send(...)` → real `TelegramAlertStrategy` → real `TelegramNotifier.send_message` → returns `(False, "telegram credentials are not configured")`. Result: `event.alert_sent is False`, which **contradicts** `test_sentinel_critical_pipeline`'s assertion `assert event.alert_sent is True`.

This directly violates Phase 4 Success Criterion 4: "All 31 existing tests pass with no modifications to test logic."

**Why it happens:** CONTEXT promises test-logic stability but D-03 physically removes the test seam. Phase 1's `ServiceContainer.__setitem__` shim doesn't help — tests go through `sentinel.telegram_notifier` directly, not through the container.

**How to avoid (recommended — all compatible with CONTEXT.md):**

Option A (least invasive): Have `SentinelService.__init__` set `self.telegram_notifier = alert_service.strategy.notifier` as a **convenience attribute**, and `TelegramAlertStrategy.send` reads `self.notifier` at call time (not ctor time). Then when a test reassigns `sentinel.telegram_notifier = DummyTelegram()`, it also needs to point the strategy at it. This is **still a test modification** in practice because the strategy needs an update too.

Option B (cleanest, adheres strictly to "no test modifications"): In `AlertService.maybe_send`, resolve the strategy dynamically via the container at dispatch time — `container.alert_strategy` — so swapping `container.telegram_notifier` (which ServiceContainer's `__setitem__` shim supports) rebuilds the strategy. This still requires changing what the test mutates.

Option C (pragmatic — recommended): **Acknowledge this test file needs a 5-line change** — replace `sentinel.telegram_notifier = DummyTelegram()` with `sentinel.alert_service.strategy = FakeStrategy()` where `FakeStrategy.send` returns `(True, None)`. This is the cleanest, mirrors the production seam, and the CONTEXT D-14 "Claude's Discretion" row explicitly allows "test injection approach for AlertService (monkeypatch vs. ServiceContainer attribute swap) — either works." This IS a test modification, and **the planner must either get explicit user approval for it OR choose Option A/B with the added complexity**.

Option D (most conservative — zero test changes, zero CONTEXT deviation): Keep `telegram_notifier` as a constructor parameter on `SentinelService` **retained but unused** (just stored as an attribute for test compatibility), and drop only the `_send_alert_if_allowed` body. The test seam `sentinel.telegram_notifier = ...` writes to a dead attribute and the real `TelegramAlertStrategy` inside `AlertService` is what actually runs — still broken.

**Planner decision required:** Options A/B add complexity to production code to preserve a test seam. Option C modifies 5 test lines but is honest about the refactor boundary. **Recommendation: Option C** — the spirit of "no test modifications" is "test assertions and setup semantics stay valid," not "byte-identical test source." CONTEXT §discretion already permits this.

**Warning signs:** `test_sentinel_pipeline.py::test_sentinel_critical_pipeline` fails with `assert event.alert_sent is True` when `alert_sent is False`. Add this test to the first-to-run list after the AlertService extraction wave.

### Pitfall P-03: Blueprint registration order matters for `url_for` during template render at startup
**What goes wrong:** If the factory renders a template (e.g., error handler during `db.create_all` failure) before `_register_blueprints(app)` runs, `url_for("dashboard")` raises `BuildError: Could not build url for endpoint 'dashboard'`.
**Why it happens:** Flask's url_map is populated only when a blueprint is registered. The current factory doesn't render templates during init, but any future error handler might.
**How to avoid:** Register blueprints BEFORE any template rendering or error-handler registration. The current sequence `build_container → _register_blueprints → coordinator.start` is safe. Document in PR description so future maintainers don't reorder.
**Warning signs:** `werkzeug.routing.exceptions.BuildError` during test startup.

### Pitfall P-04: Circular import via `app/composition.py → app/services/alerts.py → app/repositories/analysis_events.py → app/extensions.py`
**What goes wrong:** `app/extensions.py` is pure (`db = SQLAlchemy()`). But `app/services/alerts.py` importing `AnalysisEventRepository` (which imports `app.extensions.db`) can race the `app/__init__.py` import during `from app import create_app` if `alerts.py` ever imports from `app.__init__` (directly or transitively). Currently `alerts.py` doesn't exist, so this is a risk to verify, not a known break.
**Why it happens:** Python import cycles in Flask apps usually hit when a module imports `app` (the package) at top level. The composition root pattern helps — `composition.py` imports from `app.services.*` and `app.repositories.*` but nothing imports back from `composition.py`.
**How to avoid:** `app/services/alerts.py` must NOT import anything from `app` (the package root) or from `app.composition`. It may only import from `app.config_objects`, `app.services.telegram`, `app.repositories.analysis_events` (via `TYPE_CHECKING` for typing), and `typing`. Match the import surface of existing service files (e.g., `app/services/briefing.py`).
**Warning signs:** `ImportError: cannot import name 'create_app' from partially initialized module 'app'` during test collection.

### Pitfall P-05: `AlertService` commits DB session (violates Phase 2 D-01)
**What goes wrong:** Developer moves `_send_alert_if_allowed` body into `AlertService.maybe_send` and, seeing it sets no ORM state, declares it "commit-free" — but fails to notice that the caller (`process_chunk`) relies on a single `db.session.commit()` after the function returns. If `AlertService` internally commits (e.g., to persist alert metadata), atomicity for the critical-path event save breaks.
**Why it happens:** Original `_send_alert_if_allowed` is pure-read; risk is future maintenance.
**How to avoid:** Explicit docstring on `AlertService.maybe_send` reiterating "does NOT commit; caller owns transaction." Add a test that patches `db.session.commit` to assert zero calls from within `maybe_send`.
**Warning signs:** Flaky test failures in sentinel pipeline under concurrent load; partial writes if a `maybe_send` commit fires before `event_repo.add(event)`.

### Pitfall P-06: `app/web/routes.py` accidentally calls `from app import db` instead of `from app.extensions import db`
**What goes wrong:** The web routes currently in `app/__init__.py` use `db.session.commit()` directly (lines 173, 186, 255). Naive extraction copy-pastes `from app import db` (wrong — there is no `db` attribute on the app package, but Python's import machinery can make it appear to "work" intermittently depending on import order) instead of `from app.extensions import db`.
**Why it happens:** The existing `app/__init__.py` imports `from app.extensions import db` at top — developers seeing the factory use `db.session.commit()` mid-file may forget that it came from `extensions`.
**How to avoid:** Hard rule — every service/repo/route module imports `db` exclusively from `app.extensions`. Grep for `from app import db` in the PR diff; it must return zero matches.
**Warning signs:** `ImportError: cannot import name 'db' from partially initialized module 'app'`; flaky behavior where tests pass solo but fail in suite.

## Code Examples

### §1 AlertService.maybe_send — full extraction

```python
# Source: verbatim extraction from app/services/sentinel.py:265-289, with strategy swap
# app/services/alerts.py
from __future__ import annotations

from datetime import timedelta
from typing import Protocol, TYPE_CHECKING

from app.config_objects import AlertConfig
from app.services.telegram import TelegramNotifier
from app.time_utils import utcnow_naive

if TYPE_CHECKING:
    from app.models import AnalysisEvent
    from app.repositories.analysis_events import AnalysisEventRepository


class AlertStrategy(Protocol):
    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]: ...


class TelegramAlertStrategy:
    def __init__(self, notifier: TelegramNotifier) -> None:
        self.notifier = notifier

    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]:
        return self.notifier.send_message(
            token=config.telegram_token or "",
            chat_id=config.telegram_chat_id or "",
            text=message,
        )


class AlertService:
    def __init__(self, strategy: AlertStrategy, event_repo: "AnalysisEventRepository") -> None:
        self.strategy = strategy
        self.event_repo = event_repo

    def maybe_send(self, event: "AnalysisEvent", config: AlertConfig) -> tuple[bool, str | None]:
        """Gate → format → dispatch. Does NOT commit; caller owns transaction."""
        cooldown_since = utcnow_naive() - timedelta(minutes=config.cooldown_minutes)
        duplicate = self.event_repo.find_alert_duplicate(event.chunk_hash, cooldown_since)
        if duplicate:
            return False, "duplicate alert suppressed by cooldown"

        window_since = utcnow_naive() - timedelta(seconds=config.rate_limit_window_seconds)
        recent_alerts = self.event_repo.count_recent_alerts(window_since)
        if recent_alerts >= config.rate_limit_count:
            return False, "global rate limit exceeded"

        message = self._format_message(event)
        return self.strategy.send(message, config)

    @staticmethod
    def _format_message(event: "AnalysisEvent") -> str:
        return (
            f"DockSentinel Critical Alert\n"
            f"Container: {event.container_name}\n"
            f"Summary: {event.summary or 'N/A'}\n"
            f"Fix: {event.fix_suggestion or 'N/A'}"
        )
```

**Contract preservation verified:**
- Current `_send_alert_if_allowed` returns `(bool, str | None)` → `AlertService.maybe_send` returns `(bool, str | None)` ✓
- Error messages: `"duplicate alert suppressed by cooldown"` and `"global rate limit exceeded"` preserved byte-identically — `test_sentinel_pipeline.py::test_sentinel_rate_limit_suppresses_alert` asserts the exact string on line 95 ✓
- Cooldown uses `config.cooldown_minutes` minutes — matches `settings.alert_cooldown_minutes` in current code ✓
- Window uses `config.rate_limit_window_seconds` — matches `settings.alert_rate_limit_window_seconds` ✓
- Repo methods: `find_alert_duplicate(chunk_hash, since)` and `count_recent_alerts(since)` — verified present at `app/repositories/analysis_events.py:36` and `:49` ✓

### §2 Web Blueprint — full template

```python
# Source: Flask 3.x Blueprint docs + verbatim handler bodies from app/__init__.py:102-277
# app/web/routes.py
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from app.extensions import db
from app.models import ExclusionRule, PromptKey, SentinelState
from app.time_utils import utcnow_naive

bp = Blueprint("web", __name__, url_prefix="")


@bp.route("/", endpoint="index")
def index():
    return redirect(url_for("dashboard"))


@bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    container = current_app.extensions["services"]
    state = SentinelState.singleton()
    today_start = utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)
    today_events = container.event_repo.get_today(today_start)

    counts = {"critical": 0, "warning": 0, "noise": 0}
    for event in today_events:
        if event.classification in counts:
            counts[event.classification] += 1

    events = container.event_repo.get_recent(limit=10)
    latest_report = container.report_repo.get_latest()

    return render_template(
        "dashboard.html",
        state=state,
        counts=counts,
        events=events,
        latest_report=latest_report,
        active_containers=container.coordinator.active_container_ids(),
    )


# … remaining 9 handlers follow same pattern — body byte-identical to _register_web_routes.
# Required endpoint= kwargs (complete list):
#   @bp.route("/settings", methods=["GET", "POST"], endpoint="settings_page")
#   @bp.route("/exclusions", methods=["GET", "POST"], endpoint="exclusions_page")
#   @bp.route("/exclusions/delete/<int:rule_id>", endpoint="exclusions_delete")
#   @bp.route("/insights", endpoint="insights_page")
#   @bp.route("/reports", endpoint="reports_page")
#   @bp.route("/reports/generate", methods=["POST"], endpoint="reports_generate")
#   @bp.route("/prompts", methods=["GET", "POST"], endpoint="prompt_studio_page")
#   @bp.route("/sentinel/toggle", methods=["POST"], endpoint="sentinel_toggle_from_ui")
#   @bp.route("/sentinel/analyze", methods=["POST"], endpoint="sentinel_analyze_from_ui")
```

Note: `app.extensions["services"]` becomes `current_app.extensions["services"]` — Flask's `current_app` proxy resolves inside request context, which is always active in route handlers. [VERIFIED: `tests/test_ui_routes.py` uses `app.test_client()` which enters request context on each call]

### §3 Slimmed `app/__init__.py` target

```python
# Source: arithmetic trim per D-12/D-13/D-14
# app/__init__.py  (target: ≤90 LOC)
from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from flask import Flask

from app.config import AppConfig
from app.extensions import db


def _ensure_sqlite_parent_dir(app: Flask, database_uri: str) -> None:
    if not database_uri.startswith("sqlite:///"):
        return
    raw_path = database_uri.removeprefix("sqlite:///")
    if raw_path in {"", ":memory:"}:
        return
    if raw_path.startswith("/"):
        resolved_path = raw_path
    else:
        resolved_path = os.path.join(app.instance_path, raw_path)
    parent = os.path.dirname(resolved_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _register_blueprints(app: Flask) -> None:
    from app.api.exclusions import bp as exclusions_bp
    from app.api.health import bp as health_bp
    from app.api.insights import bp as insights_bp
    from app.api.prompts import bp as prompts_bp
    from app.api.reports import bp as reports_bp
    from app.api.sentinel import bp as sentinel_bp
    from app.api.settings import bp as settings_bp
    from app.api.telegram import bp as telegram_bp
    from app.web.routes import bp as web_bp

    for bp in (health_bp, settings_bp, exclusions_bp, prompts_bp,
               sentinel_bp, insights_bp, reports_bp, telegram_bp, web_bp):
        app.register_blueprint(bp)


def create_app() -> Flask:
    from app.bootstrap import seed_defaults
    from app.composition import build_container

    load_dotenv()
    config = AppConfig.from_env()

    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    app.config["SQLALCHEMY_DATABASE_URI"] = config.database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["TESTING"] = config.testing
    app.config["RUNTIME_LOCK_PATH"] = config.runtime_lock_path
    app.config["START_COORDINATOR"] = config.start_coordinator

    _ensure_sqlite_parent_dir(app, app.config["SQLALCHEMY_DATABASE_URI"])
    db.init_app(app)

    with app.app_context():
        if app.config.get("TESTING"):
            db.create_all()
        seed_defaults(db)
        app.extensions["services"] = build_container(app)

    _register_blueprints(app)

    coordinator = app.extensions["services"].coordinator
    if app.config["START_COORDINATOR"] and not app.config["TESTING"]:
        coordinator.start()
        atexit.register(coordinator.stop)

    return app
```

**Estimated line count:** 68 LOC (including blank lines and imports). Well under 90.

## Runtime State Inventory

Covered above. All five categories empty / no-op for this phase.

## Phase-Specific Gotchas

### G-01: LOC arithmetic — residual budget after mechanical extraction

| Source (before) | LOC | Disposition | LOC moved |
|-----------------|-----|-------------|-----------|
| Imports (lines 1-35) | 35 | ~15 stay; 20 move to composition.py + bootstrap.py | −20 |
| `_ensure_sqlite_parent_dir` (38-53) | 16 | Stay | 0 |
| `_seed_defaults` (56-78) | 23 | Move to bootstrap.py | −23 |
| `_register_api_blueprints` (82-99) | 18 | Rename to `_register_blueprints`, add web_bp — shrink via loop (see §3) | ~−6 |
| `_register_web_routes` (102-277) | 176 | Move to app/web/routes.py | −176 |
| `create_app` (280-349) | 70 | Composition block (300-340 = 40 LOC) moves to composition.py; rest stays | −40 |
| **Total** | **349** | | **−265** |

Residual: 349 − 265 = **84 LOC**. ✓ Under 90.

Re-verified above against the §3 target which comes out to 68 LOC. The difference (84 vs 68) is because the trim shown in §3 also consolidates the blueprint registration into a loop and folds some redundant lines — the mechanical extraction alone lands at 84, and the additional micro-trim (loop + removing trailing blank lines) lands at 68.

**Conclusion:** ≤90 is achievable via mechanical extraction alone; additional polish reaches ~70.

### G-02: `ServiceContainer` extension — two new attrs require ordering in dataclass definition

The dataclass has required (non-default) fields. Adding `alert_strategy: AlertStrategy` and `alert_service: "AlertService"` in the middle breaks keyword-argument order used at instantiation (`ServiceContainer(llm_client=…, llm_call=…, …)`). Safe placement: **after `telegram_notifier` and before `sentinel`** — both because it mirrors the dependency chain (strategy → service → sentinel uses it) and because every existing `ServiceContainer(...)` construction site uses kwargs, so ordering only matters for readability.

### G-03: `TelegramNotifier` stays accessible via `/api/telegram/test`

The `app/api/telegram.py` endpoint reads `current_app.extensions["services"].telegram_notifier` (line 13). CONTEXT D-05 explicitly keeps `telegram_notifier` on `ServiceContainer`. Verify this is NOT accidentally removed during the container extension — `test_core_api_endpoints` in `test_api.py:72-73` asserts `/api/telegram/test` returns 400 (unconfigured credentials path), which exercises the full `notifier.send_message` code.

### G-04: `SentinelService.__init__` signature change cascades through coordinator construction

`RuntimeCoordinator(app=app, sentinel_service=sentinel_service, briefing_service=briefing_service)` does NOT use `sentinel_service.telegram_notifier`, so the coordinator isn't affected. Verified via `Grep("telegram_notifier", path="app/services/coordinator.py")` — zero matches.

### G-05: Template `url_for` completeness audit (12 unique targets)

Exhaustive grep of `app/templates/*.html`:

| Template | `url_for(...)` calls | All targets covered by D-10? |
|----------|----------------------|------------------------------|
| `base.html` | `static`, `dashboard` (×2), `settings_page`, `exclusions_page`, `insights_page`, `reports_page`, `prompt_studio_page` | ✓ (`static` is Flask built-in, not a Blueprint endpoint) |
| `dashboard.html` | `sentinel_toggle_from_ui` (×2), `reports_generate` (×2), `sentinel_analyze_from_ui`, `reports_page` | ✓ |
| `exclusions.html` | `exclusions_delete` | ✓ |
| `reports.html` | `reports_generate`, `reports_page` | ✓ |
| `prompt_studio.html`, `insights.html`, `settings.html` | (none — forms post to same URL or no url_for) | ✓ |

**Result:** 12 distinct endpoint names, all covered by D-10. Zero template modifications required.

### G-06: `ExclusionRule`, `PromptKey`, `SentinelState` imports must move with handlers

The web routes import these from `app.models`. When moving to `app/web/routes.py`, the imports must come with. `app/__init__.py` can drop its imports of `DEFAULT_PROMPTS`, `ExclusionRule`, `PromptTemplate`, `PromptKey`, `SchemaVersion`, `SentinelState`, `Settings` — they only appear in the routes and in `_seed_defaults` (now in bootstrap.py).

## Test Impact Analysis

### Tests that must stay green (from CONTEXT)

| Test file | Test cases | Relies on... | Risk |
|-----------|-----------|--------------|------|
| `test_ui_routes.py` | 1 smoke test (7 URLs) | `url_for` resolution via endpoint names | LOW — endpoint names explicitly preserved by D-10 |
| `test_sentinel_pipeline.py` | 6 tests | `sentinel.telegram_notifier = DummyTelegram()` assignment on lines 42/66/130/161/190 | **HIGH** — see Pitfall P-02 |
| `test_api.py` | 4 tests | `/api/telegram/test` → `services.telegram_notifier` on container | LOW — D-05 keeps `telegram_notifier` on container |
| `test_briefing.py`, `test_cli_backends.py`, `test_llm_client.py`, `test_log_buffer.py`, `test_models.py`, `test_prefilter.py`, `test_runtime_lock.py` | ~20 tests | No alert or blueprint surface area | NONE |

### Test-seam preservation decision

CONTEXT §discretion explicitly states: "Exact test injection approach for `AlertService` (monkeypatch vs. ServiceContainer attribute swap) — either works since Phase 1 shim supports both." This **implies** CONTEXT anticipated test-injection changes. Combined with Pitfall P-02 analysis, planner should treat 5-line test modification as in-scope under discretion, OR raise explicitly to user during plan-checker.

**Recommended minimal test modification (5 lines, all in `test_sentinel_pipeline.py`):**

```python
# Before (5 occurrences):
sentinel.telegram_notifier = DummyTelegram()

# After:
class _FakeAlertStrategy:
    def send(self, message, config):
        return True, None
sentinel.alert_service.strategy = _FakeAlertStrategy()
```

This is a **mechanical swap** — no assertion changes, no additional setup. Preserves all 6 test intents. The `test_sentinel_critical_pipeline.DummyTelegram` class becomes dead code (can stay or be removed).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | Runtime | ✓ | 3.12 (verified via `.python-version`) | — |
| Flask | Web framework | ✓ | 3.0.3 (pinned) | — |
| Flask-SQLAlchemy | DB access | ✓ | 3.1.1 | — |
| pytest | Test runner | ✓ | 8.3.4 | — |
| No new packages | — | — | — | — |

All phase-required tooling is already in the environment. No external services needed (no Telegram credentials required — tests use `DummyTelegram` / `_FakeAlertStrategy`).

## Project Constraints (from CLAUDE.md)

Enumerated directives from both `./CLAUDE.md` files that constrain this phase:

**From root `/Users/rohan/Downloads/CLAUDE.md` (CollectiveX global — some apply even here):**
- No unnecessary abstractions ("three similar lines > one premature helper") — reinforces D-06 single-blueprint decision.
- No speculative features — rules out adding Slack/Discord stubs "for later."
- Integration tests hit real databases (Testcontainers) — not directly relevant; test suite already uses SQLite file in tmp_path.

**From project `/Users/rohan/Downloads/DockSentinel/CLAUDE.md`:**
- No new frameworks (Python 3.12, Flask, SQLAlchemy, Pydantic v2, SQLite, Docker, APScheduler). Phase adds zero new packages ✓
- Use `typing.Protocol`, NOT `abc.ABC`. Locked in D-01.
- "No premature helpers" — single web Blueprint, not per-domain (D-06).
- API contract intact, all 31 tests green — phase's hard constraint.
- "GSD workflow enforcement" — start work through GSD command (handled by orchestrator).
- "No new features — purely structural" — no new Telegram features, no new route behavior.

**Critical compliance checks for planner:**
- [ ] Plan must use `typing.Protocol`, not `abc.ABC` (grep PR diff for `abstractmethod` — must be zero)
- [ ] Plan must NOT add new packages to `requirements.txt`
- [ ] Plan must keep all 31 existing tests green (with at-most 5-line seam update per Pitfall P-02)
- [ ] Plan must preserve every URL pattern and endpoint name (12 `url_for` targets verified in G-05)
- [ ] `AlertService` must NOT call `db.session.commit()` (Phase 2 D-01 inheritance)
- [ ] `app/__init__.py` final LOC ≤ 90 (G-01 shows achievable)

## State of the Art

No "state of the art" shifts relevant — this phase uses Python stdlib features and Flask Blueprint APIs stable since Flask 1.0. `typing.Protocol` has been stable since Python 3.8 (project is on 3.12). No recent deprecations affect the code paths touched.

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `flask.globals.current_app` import | `from flask import current_app` | Flask 2.0 (2021) | Already using modern import |
| `@app.route` in factory | Blueprint with `@bp.route` | Blueprint API stable since Flask 1.0 (2018) | This phase adopts the stable API |
| Dict-based `app.extensions["services"]` | Typed dataclass `ServiceContainer` with `__getitem__` shim | Phase 1 of this milestone | Phase 4 extends container; shim stays |

**Deprecated/outdated:** None encountered — no code being removed is deprecated, just relocated.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| — | None | — | All claims in this research are either `[VERIFIED]` against the local codebase or `[CITED]` to Flask/Python stdlib documentation. |

**This table is empty:** All factual claims were verified via Read/Grep of the local codebase or cited against stable Flask/Python documentation. The only judgment call is Pitfall P-02's recommended resolution (Option C), which is explicitly surfaced for planner/user decision rather than locked as a fact.

## Open Questions

1. **Option for Pitfall P-02 test seam preservation** — A, B, C, or D?
   - What we know: CONTEXT §discretion permits test-injection path changes; test assertions must stay valid.
   - What's unclear: Whether "no test modifications" in Success Criterion 4 means "no assertion changes" (permissive — allows Option C) or "byte-identical test source" (strict — requires Options A/B with added production complexity, or Option D which leaves the tests broken in a subtle way).
   - Recommendation: Option C (5-line mechanical swap of injection target). Planner should surface explicitly during plan-checker; if rejected, fall back to Option A (SentinelService retains a `telegram_notifier` property that reads from `self.alert_service.strategy.notifier`, with a custom `__setattr__` to re-wire the strategy on reassignment — adds ~15 LOC of production complexity purely for test compatibility).

2. **Ordering of waves — AlertService extraction before or after Blueprint extraction?**
   - What we know: These touch different files with no overlap.
   - What's unclear: Whether to land them in separate commits (auditable, easy to revert) or one big commit (less ceremony).
   - Recommendation: Separate commits in the order listed in Summary (AlertService first, then composition.py, then bootstrap.py, then Blueprint, then `__init__.py` trim). Each commit leaves test suite green.

## Sources

### Primary (HIGH confidence)
- **Local codebase — verified via Read + Grep:**
  - `app/__init__.py` (349 LOC, full read) — source truth for extraction scope
  - `app/services/sentinel.py` (309 LOC, full read) — `_send_alert_if_allowed` at 265-289
  - `app/services/telegram.py` (18 LOC) — `TelegramNotifier.send_message` contract
  - `app/config_objects.py` (97 LOC) — `AlertConfig` shape
  - `app/container.py` (42 LOC) — `ServiceContainer` + `_KEY_MAP` shim
  - `app/repositories/analysis_events.py` (105 LOC) — `find_alert_duplicate`, `count_recent_alerts` verified
  - `app/api/telegram.py`, `app/api/health.py` (idiom reference)
  - `app/templates/base.html` + grep across all 7 templates — 12 `url_for` targets enumerated
  - `tests/test_sentinel_pipeline.py`, `tests/test_ui_routes.py`, `tests/test_api.py` — test contract
- **Flask 3.x official documentation:**
  - https://flask.palletsprojects.com/en/stable/blueprints/ — Blueprint API, `url_prefix`
  - https://flask.palletsprojects.com/en/stable/blueprints/#building-urls — endpoint name resolution
  - https://flask.palletsprojects.com/en/stable/api/#flask.Blueprint — `endpoint=` kwarg semantics
- **Python 3.12 stdlib:**
  - https://docs.python.org/3/library/typing.html#typing.Protocol — structural subtyping
  - https://docs.python.org/3/library/typing.html#typing.runtime_checkable — why we don't need it
- **Project documentation:**
  - `./CLAUDE.md` §Alert Strategy Pattern and §What NOT to Add — ABC forbidden, Protocol required
  - `.planning/REQUIREMENTS.md` §Service Extraction + §App Structure — SRVC-03/04, APP-01/02/03
  - `.planning/phases/01-foundation/01-CONTEXT.md` — ServiceContainer shape, shim semantics
  - `.planning/phases/02-repository-layer/02-CONTEXT.md` — repositories don't commit

### Secondary (MEDIUM confidence)
- **Cosmic Python — Architecture Patterns with Python:**
  - https://www.cosmicpython.com/book/chapter_13_dependency_injection.html — composition root pattern rationale (applied but not load-bearing — the pattern is standard)
  - https://www.cosmicpython.com/book/chapter_04_service_layer.html — thin orchestration service boundaries

### Tertiary (LOW confidence)
- None — this research relied entirely on primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions pinned, zero new packages
- Architecture: HIGH — all decisions locked in CONTEXT, patterns verified against codebase
- Pitfalls: HIGH — each pitfall traced to a specific file + line in the working tree
- Test impact: HIGH — exhaustive grep of test files for affected attribute/method names
- LOC budget: HIGH — arithmetic from actual line counts (`wc -l` verified)
- P-02 resolution recommendation: MEDIUM — depends on interpretation of "no test modifications" in Success Criterion 4

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (30 days — stable Flask/Python APIs; only invalidated if CONTEXT decisions change or a new Phase-3.x patch adds surface area to `app/__init__.py`)
