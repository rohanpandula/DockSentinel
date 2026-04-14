# Phase 4: Service Decomposition and Blueprint - Pattern Map

**Mapped:** 2026-04-14
**Files analyzed:** 9 (5 NEW, 4 MODIFIED)
**Analogs found:** 9 / 9 (every target has a direct in-repo analog)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| **NEW** `app/services/alerts.py` | service (+ transport strategy) | request-response (gate → format → dispatch) | `app/services/briefing.py` (service ctor + repo deps) + `app/services/telegram.py` (transport wrapper) + `app/services/sentinel.py::_send_alert_if_allowed` (verbatim logic source) | exact (logic lifted byte-identically) |
| **NEW** `app/web/__init__.py` | config (package marker) | n/a | `app/repositories/__init__.py` (1-line empty package marker) | exact |
| **NEW** `app/web/routes.py` | controller (web/HTML) | request-response (render_template / redirect) | `app/api/insights.py` + `app/api/prompts.py` (Blueprint + `current_app.extensions["services"]` access + `db.session.commit()` pattern) | role-match (API returns JSON; web returns HTML — same Blueprint mechanics) |
| **NEW** `app/composition.py` | config (composition root) | batch (one-shot wiring) | `app/__init__.py` lines 300–340 (current inline wiring) | exact (straight relocation) |
| **NEW** `app/bootstrap.py` | config (seed script) | batch (one-shot seeding) | `app/__init__.py::_seed_defaults` lines 56–78 | exact (straight relocation) |
| **MODIFIED** `app/__init__.py` | config (app factory) | batch (startup wiring) | Self (trim in place) — reference target at RESEARCH §3 | exact |
| **MODIFIED** `app/services/sentinel.py` | service | request-response | Self — constructor signature + `process_chunk` alert trigger change | exact (minimal surgical edit) |
| **MODIFIED** `app/container.py` | config (typed DI container) | n/a | Self — extend dataclass with 2 typed attrs; mirror existing `TYPE_CHECKING` pattern | exact |
| **MODIFIED** `tests/test_sentinel_pipeline.py` | test | n/a | Self — 5-line seam swap per RESEARCH P-02 Option C | exact |

---

## Pattern Assignments

### `app/services/alerts.py` (NEW — service + strategy)

**Primary analog:** `app/services/briefing.py` (service class with typed repo deps + `TYPE_CHECKING` imports)
**Secondary analog:** `app/services/telegram.py` (thin HTTP-transport class)
**Logic source:** `app/services/sentinel.py` lines 265–289 (`_send_alert_if_allowed` — body is copied verbatim, then `self.telegram_notifier.send_message(...)` is replaced by `self.strategy.send(message, config)`)

**Imports pattern** — copy from `app/services/briefing.py` lines 1–17 (stdlib → app.config_objects → app.extensions → app.models → `TYPE_CHECKING` for repo types):
```python
from __future__ import annotations

from datetime import timedelta
from typing import Protocol, TYPE_CHECKING

from app.config_objects import AlertConfig
from app.services.telegram import TelegramNotifier
from app.time_utils import utcnow_naive

if TYPE_CHECKING:
    from app.models import AnalysisEvent
    from app.repositories.analysis_events import AnalysisEventRepository
```

Rationale: identical shape to `briefing.py` — `from __future__ import annotations`, absolute `app.*` imports only, `TYPE_CHECKING` guard around repo and model types to avoid circular imports (Pitfall P-04 in RESEARCH).

**Protocol + strategy pattern** (new, no in-repo analog for Protocol yet — but follows RESEARCH §Code Examples §1 verbatim, which itself matches CLAUDE.md §Alert Strategy Pattern):
```python
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

Notes:
- Do NOT add `@runtime_checkable` — no `isinstance()` check exists in the codebase (verified).
- `TelegramAlertStrategy` delegates to the existing `TelegramNotifier.send_message` — its return type `tuple[bool, str | None]` already matches the Protocol (see `app/services/telegram.py` line 7).

**Service ctor pattern** — copy from `app/services/briefing.py` lines 19–30:
```python
class AlertService:
    def __init__(self, strategy: AlertStrategy, event_repo: "AnalysisEventRepository") -> None:
        self.strategy = strategy
        self.event_repo = event_repo
```

**Core gating pattern** — lift verbatim from `app/services/sentinel.py` lines 265–289, replace transport call:
```python
def maybe_send(self, event: "AnalysisEvent", config: AlertConfig) -> tuple[bool, str | None]:
    """Gate -> format -> dispatch. Does NOT commit; caller owns transaction."""
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

**Contract preservation** (required — verified against `tests/test_sentinel_pipeline.py`):
- Error string `"duplicate alert suppressed by cooldown"` — asserted on test line 151.
- Error string `"global rate limit exceeded"` — asserted on test line 95.
- Tuple return shape `(bool, str | None)` — propagates through to `event.alert_sent` / `event.alert_error`.

**No-commit rule** (Phase 2 D-01 inherited): `AlertService.maybe_send` must NEVER call `db.session.commit()`. Verify: the body above contains zero `db.session` references (no import of `db` in this file at all — intentional).

---

### `app/web/__init__.py` (NEW — empty package marker)

**Analog:** `app/repositories/__init__.py` (1 blank line — empty package marker). Follow this exact pattern. No imports, no `__all__`, no re-exports. The file exists solely to mark `app/web/` as a Python package.

---

### `app/web/routes.py` (NEW — web Blueprint, 11 handlers)

**Primary analog:** `app/api/insights.py` (Blueprint with `current_app.extensions["services"]` access + query-param parsing + `_parse_dt` helper)
**Secondary analog:** `app/api/prompts.py` (Blueprint with `db.session.commit()` directly in handlers — exact pattern the current web routes use on lines 173, 186, 255 of `app/__init__.py`)
**Handler-body source:** `app/__init__.py` lines 102–277 (every handler body copied byte-identically — only the decorator line changes)

**Imports pattern** — blend `app/api/insights.py` lines 1–7 with the models currently imported by the routes in `app/__init__.py`:
```python
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, redirect, render_template, request, url_for

from app.extensions import db
from app.models import ExclusionRule, PromptKey, SentinelState
from app.time_utils import utcnow_naive
```

Critical rule from RESEARCH Pitfall P-06: `db` MUST be imported from `app.extensions`, never `from app import db`. Grep the PR diff for `from app import db` — must return zero matches.

**Blueprint declaration pattern** — analog `app/api/insights.py` line 7:
```python
bp = Blueprint("web", __name__, url_prefix="")
```
Differs from API blueprints in two ways: blueprint name is `"web"` (not `"<domain>_api"`), and `url_prefix=""` (not `"/api"`).

**Route decorator pattern** — analog `app/api/insights.py` line 19, with the mandatory `endpoint=` kwarg addition per D-10:
```python
@bp.route("/", endpoint="index")
def index():
    return redirect(url_for("dashboard"))


@bp.route("/dashboard", endpoint="dashboard")
def dashboard():
    container = current_app.extensions["services"]
    # ... body byte-identical to current app/__init__.py lines 108-129 ...
```

**Full endpoint mapping** (every decorator MUST set `endpoint=` explicitly — failing to do so causes Flask to auto-prefix with `"web."`, breaking every `url_for()` call in templates):

| URL | Methods | `endpoint=` kwarg | Source lines in `app/__init__.py` |
|-----|---------|-------------------|-----------------------------------|
| `/` | GET | `"index"` | 103–105 |
| `/dashboard` | GET | `"dashboard"` | 107–129 |
| `/settings` | GET, POST | `"settings_page"` | 131–162 |
| `/exclusions` | GET, POST | `"exclusions_page"` | 164–178 |
| `/exclusions/delete/<int:rule_id>` | GET | `"exclusions_delete"` | 180–188 |
| `/insights` | GET | `"insights_page"` | 190–219 |
| `/reports` | GET | `"reports_page"` | 221–227 |
| `/reports/generate` | POST | `"reports_generate"` | 229–232 |
| `/prompts` | GET, POST | `"prompt_studio_page"` | 234–259 |
| `/sentinel/toggle` | POST | `"sentinel_toggle_from_ui"` | 261–266 |
| `/sentinel/analyze` | POST | `"sentinel_analyze_from_ui"` | 268–277 |

**Handler body rule:** Copy verbatim from `app/__init__.py`. The only permitted edit is substituting `app.extensions["services"]` with `current_app.extensions["services"]` (Flask's request-bound proxy — see `app/api/insights.py` line 21 for precedent). Do NOT refactor handler bodies, do NOT introduce new helpers — this is pure code motion.

**`db.session.commit()` pattern** — copy from `app/api/prompts.py` line 32 (direct call inside handler, after ORM state mutation). Matches current inline calls at `app/__init__.py` lines 173, 186, 255.

---

### `app/composition.py` (NEW — composition root)

**Analog:** `app/__init__.py` lines 300–340 (current inline service wiring). Straight relocation.

**Imports pattern** — absolute imports of everything the composition block instantiates. See RESEARCH §Code Examples §3 for full list. Key additions over the current factory: `from app.services.alerts import AlertService, TelegramAlertStrategy`.

**Function signature pattern** — no precise analog (new composition-root file), but mirrors how `app/services/briefing.py` ctor accepts multiple deps:
```python
from __future__ import annotations

import os
from flask import Flask

from app.container import ServiceContainer
# ... all repo + service imports ...
from app.services.alerts import AlertService, TelegramAlertStrategy


def build_container(app: Flask) -> ServiceContainer:
    # Dependency order: repos -> clients -> services -> strategy -> services needing strategy -> coordinator
    ...
    return ServiceContainer(...)
```

**Wiring pattern** — copy verbatim from `app/__init__.py` lines 300–340, with these required changes:
1. Drop `telegram_notifier=telegram_notifier` from `SentinelService(...)` constructor call (line 314).
2. Add `alert_service=alert_service` to `SentinelService(...)` constructor call.
3. Insert two new lines before the `SentinelService(...)` call:
   ```python
   alert_strategy = TelegramAlertStrategy(telegram_notifier)
   alert_service = AlertService(strategy=alert_strategy, event_repo=event_repo)
   ```
4. Add `alert_strategy=alert_strategy,` and `alert_service=alert_service,` to the `ServiceContainer(...)` kwargs list (placement: after `telegram_notifier=`, before `sentinel=`).

**Return pattern** — exactly as `app/__init__.py` lines 327–340 (ServiceContainer kwargs), plus the two new kwargs.

---

### `app/bootstrap.py` (NEW — default data seeding)

**Analog:** `app/__init__.py::_seed_defaults` lines 56–78. Straight relocation with one interface change.

**Imports pattern** — move these from `app/__init__.py` to `app/bootstrap.py`:
```python
from __future__ import annotations

from app.extensions import db
from app.models import (
    DEFAULT_PROMPTS,
    ExclusionRule,
    PromptTemplate,
    SchemaVersion,
    SentinelState,
    Settings,
)
```

**Function pattern** — copy body verbatim from lines 56–78, renamed from `_seed_defaults` to `seed_defaults`. Per CONTEXT D-12 Claude's Discretion, signature MAY take `db` as a parameter OR import from `app.extensions` — either is compliant. Recommendation: import from `app.extensions` (zero-param function) to match how every repository already does it (see `app/repositories/analysis_events.py` line 7). Consistency > explicitness here.

```python
def seed_defaults() -> None:
    SchemaVersion.singleton()
    Settings.singleton()
    SentinelState.singleton()

    for pattern in ["docksentinel", "ollama", "portainer", "open-webui"]:
        if ExclusionRule.query.filter_by(container_pattern=pattern).first() is None:
            db.session.add(ExclusionRule(container_pattern=pattern, enabled=True))

    for key, content in DEFAULT_PROMPTS.items():
        existing = PromptTemplate.query.filter_by(key=key.value).first()
        if existing is None:
            db.session.add(
                PromptTemplate(
                    key=key.value,
                    content=content,
                    default_content=content,
                    version=1,
                    is_default=True,
                )
            )

    db.session.commit()
```

Note: `PromptKey` import is NOT needed here — `DEFAULT_PROMPTS` is already keyed by `PromptKey`, and the iteration does `key.value`. Verified via the existing `_seed_defaults` body.

---

### `app/__init__.py` (MODIFIED — trim to ≤90 LOC)

**Target shape:** RESEARCH §Code Examples §3 (the ≤90 LOC slimmed factory). This is the authoritative template. Key structural moves:

**Imports to DROP** (now belong to `composition.py` or `bootstrap.py`):
- `DEFAULT_PROMPTS, ExclusionRule, PromptTemplate, PromptKey, SchemaVersion, SentinelState, Settings` from `app.models`
- All `app.repositories.*` imports
- All `app.services.*` imports (except `atexit`-registered coordinator access which now goes via `app.extensions["services"].coordinator`)
- `ServiceContainer` import
- `utcnow_naive` from `app.time_utils`
- `redirect`, `render_template`, `request`, `url_for`, `datetime` from flask/stdlib (only routes use them)

**Imports to KEEP** (needed in the slimmed factory):
```python
from __future__ import annotations

import atexit
import os

from dotenv import load_dotenv
from flask import Flask

from app.config import AppConfig
from app.extensions import db
```

**Functions to DELETE** from this file:
- `_seed_defaults` (moved to `app/bootstrap.py`)
- `_register_web_routes` (moved to `app/web/routes.py`)

**Functions to KEEP/RENAME** (unchanged body except blueprint list):
- `_ensure_sqlite_parent_dir` — keep inline, unchanged (D-13).
- `_register_api_blueprints` → rename to `_register_blueprints`; add `from app.web.routes import bp as web_bp` and register it alongside the 8 API blueprints. Optionally consolidate registrations into a single for-loop (RESEARCH §3 shows this; saves 7 lines).

**`create_app()` body** — follow RESEARCH §Code Examples §3 lines 686–717 exactly:
```python
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
        seed_defaults()
        app.extensions["services"] = build_container(app)

    _register_blueprints(app)

    coordinator = app.extensions["services"].coordinator
    if app.config["START_COORDINATOR"] and not app.config["TESTING"]:
        coordinator.start()
        atexit.register(coordinator.stop)

    return app
```

Note on local imports for `seed_defaults`/`build_container`: deferring these to function-body imports avoids Pitfall P-04 (circular import risk from top-level imports of `app.composition` in `app/__init__.py`).

**LOC budget verification** — per RESEARCH §G-01 arithmetic: 349 LOC source − 265 LOC moved = **84 LOC residual** (≤90 target ✓).

---

### `app/services/sentinel.py` (MODIFIED — drop transport, add alert_service)

**Analog:** Self. Three surgical edits only — every line not listed below stays byte-identical.

**Edit 1 — constructor signature** (lines 23–39):
- Remove parameter `telegram_notifier: Any,` (line 28)
- Remove assignment `self.telegram_notifier = telegram_notifier` (line 35)
- Add parameter `alert_service: "AlertService",` (after `verdict_parser`)
- Add assignment `self.alert_service = alert_service`
- Add `TYPE_CHECKING` import: `from app.services.alerts import AlertService` under the existing `TYPE_CHECKING` block (lines 17–20) to preserve the existing no-runtime-import pattern.

**Pattern to mirror** — the existing `TYPE_CHECKING` block at `app/services/sentinel.py` lines 17–20:
```python
if TYPE_CHECKING:
    from app.repositories.analysis_events import AnalysisEventRepository
    from app.repositories.exclusions import ExclusionRepository
    from app.repositories.prompts import PromptRepository
    from app.services.alerts import AlertService  # ADD THIS LINE
```

**Edit 2 — alert trigger in `process_chunk`** (lines 255–258):
```python
# BEFORE
if verdict.classification == "critical":
    sent, alert_error = self._send_alert_if_allowed(event)
    event.alert_sent = sent
    event.alert_error = alert_error

# AFTER
if verdict.classification == "critical":
    from app.config_objects import AlertConfig  # (or hoist to top import)
    sent, alert_error = self.alert_service.maybe_send(
        event, AlertConfig.from_settings(self._settings())
    )
    event.alert_sent = sent
    event.alert_error = alert_error
```
Note: `AlertConfig` is already imported-adjacent — the file imports `LLMConfig` from `app.config_objects` at line 9. Recommendation: extend that existing import line to `from app.config_objects import AlertConfig, LLMConfig`. Matches the `from app.config_objects import LLMConfig` idiom already in place.

**Edit 3 — delete `_send_alert_if_allowed`** (lines 265–289): remove the entire method. The classification gate (`if verdict.classification == "critical"`) STAYS in `SentinelService` per CONTEXT §specifics — only the gating-and-dispatch logic moves.

**Ctor argument order note** (RESEARCH G-02): every call site uses keyword arguments, so positional order doesn't matter. Place `alert_service` after `verdict_parser` for readability (reflects dependency chain: sentinel uses verdict_parser for parsing → alert_service for dispatch).

---

### `app/container.py` (MODIFIED — extend dataclass with 2 typed attrs)

**Analog:** Self. Extend the existing `ServiceContainer` dataclass following its established pattern.

**Existing `TYPE_CHECKING` pattern to mirror** (lines 6–11 of current file):
```python
if TYPE_CHECKING:
    from app.repositories.analysis_events import AnalysisEventRepository
    # ... other repo imports ...
    from app.services.alerts import AlertService, AlertStrategy  # ADD THIS LINE
```

**Dataclass extension pattern** — insert two attrs AFTER `telegram_notifier` (line 23) and BEFORE `sentinel` (line 24). Per RESEARCH Pitfall P-01, use the real Protocol type (not `Any`) to preserve IDE/mypy value:
```python
@dataclass
class ServiceContainer:
    llm_client: Any
    llm_call: Any
    verdict_parser: Any
    telegram_notifier: Any
    alert_strategy: "AlertStrategy"    # NEW
    alert_service: "AlertService"      # NEW
    sentinel: Any
    briefing: Any
    coordinator: Any
    event_repo: AnalysisEventRepository
    settings_repo: SettingsRepository
    prompt_repo: PromptRepository
    report_repo: ReportRepository
    exclusion_repo: ExclusionRepository
```

String-quoted forward refs match the existing pattern (the repo attrs use unquoted `AnalysisEventRepository` etc. because they're under `TYPE_CHECKING` with `from __future__ import annotations`). Either style works here — prefer unquoted to match existing repo attrs:
```python
    alert_strategy: AlertStrategy
    alert_service: AlertService
```

**`_KEY_MAP` shim** (line 13): no change needed. The shim only maps the `"telegram"` short key. Tests don't access `"alert_strategy"` or `"alert_service"` via string-key `__getitem__`, so no new mappings required. (Verified via grep of tests/ for string-literal `"alert_"` access — zero matches.)

**Ordering safety** (RESEARCH G-02): every instantiation site (the future `build_container()`) uses `kwargs`, so inserting these attrs in the middle of the dataclass does NOT break any existing call. The single current call at `app/__init__.py` lines 327–340 is also all-kwargs.

---

### `tests/test_sentinel_pipeline.py` (MODIFIED — 5-line seam swap)

**Analog:** Self. Per RESEARCH Pitfall P-02 Option C (CONTEXT §discretion explicitly permits "test injection approach for AlertService — either works").

**The swap** — 5 occurrences of the same line to change:

| Line # (current) | Before | After |
|------------------|--------|-------|
| 42 | `sentinel.telegram_notifier = DummyTelegram()` | `sentinel.alert_service.strategy = _FakeAlertStrategy()` |
| 66 | `sentinel.telegram_notifier = DummyTelegram()` | `sentinel.alert_service.strategy = _FakeAlertStrategy()` |
| 130 | `sentinel.telegram_notifier = DummyTelegram()` | `sentinel.alert_service.strategy = _FakeAlertStrategy()` |
| 161 | `sentinel.telegram_notifier = DummyTelegram()` | `sentinel.alert_service.strategy = _FakeAlertStrategy()` |
| 190 | `sentinel.telegram_notifier = DummyTelegram()` | `sentinel.alert_service.strategy = _FakeAlertStrategy()` |

**New test helper** — add near `DummyTelegram` (lines 22–24) a matching Protocol-compatible fake:
```python
class _FakeAlertStrategy:
    def send(self, message, config):
        return True, None
```

**Keep or delete `DummyTelegram`:** CONTEXT §discretion allows either. Recommend KEEP (dead code but zero risk of breaking tests if any future test reintroduces the transport-level seam).

**Assertions preserved** — every `assert event.alert_sent is True`, `assert event.alert_sent is False`, `assert event.alert_error == "..."` stays byte-identical. Only the injection target changes.

---

## Shared Patterns

### Pattern S-1: Container access in route handlers (web + API)
**Source:** `app/api/insights.py` line 21 (`container = current_app.extensions["services"]`)
**Also:** `app/api/prompts.py` lines 12, 19, 38; `app/api/telegram.py` line 13
**Apply to:** Every handler in `app/web/routes.py`
**Pattern:**
```python
@bp.route(...)
def handler():
    container = current_app.extensions["services"]
    # ... use container.event_repo, container.coordinator, etc. ...
```
Rationale: Flask's `current_app` proxy resolves at request time; using `app.extensions[...]` (no proxy) — as the current inline routes do — only works because the closure captures `app`. Blueprints lose that closure, so `current_app` is mandatory.

### Pattern S-2: Blueprint module template (single `bp` symbol at module top)
**Source:** All 8 files in `app/api/` — every one exports `bp = Blueprint("<name>_api", __name__, url_prefix="/api")` at module level.
**Apply to:** `app/web/routes.py`
**Pattern:**
```python
bp = Blueprint("web", __name__, url_prefix="")
```
Rationale: Registration in `_register_blueprints` imports `bp` by name — sticking to this convention keeps the factory's import block uniform.

### Pattern S-3: `TYPE_CHECKING` for service/repo typing without runtime imports
**Source:** `app/services/briefing.py` lines 13–16; `app/services/sentinel.py` lines 17–20; `app/container.py` lines 6–11
**Apply to:** `app/services/alerts.py`, `app/container.py` (extension), `app/services/sentinel.py` (AlertService type)
**Pattern:**
```python
from __future__ import annotations

from typing import TYPE_CHECKING
# ... runtime imports ...

if TYPE_CHECKING:
    from app.repositories.analysis_events import AnalysisEventRepository
    from app.services.alerts import AlertService
```
Rationale: Prevents the circular-import class (Pitfall P-04) that would occur if `app/services/alerts.py` runtime-imported `AnalysisEventRepository` and a repo file ever imported from `app.services.alerts`.

### Pattern S-4: Service ctor accepts typed deps, stores as attrs
**Source:** `app/services/briefing.py` lines 19–30; `app/services/llm_call.py` lines 9–11; `app/services/sentinel.py` lines 24–39
**Apply to:** `AlertService.__init__` in `app/services/alerts.py`
**Pattern:**
```python
def __init__(self, strategy: AlertStrategy, event_repo: "AnalysisEventRepository") -> None:
    self.strategy = strategy
    self.event_repo = event_repo
```
No kwargs-only enforcement, no `@dataclass` on services — matches every existing service in the project.

### Pattern S-5: Frozen config dataclass as method param (not ctor param)
**Source:** `app/services/llm_call.py::call(config: LLMConfig, ...)` line 14; callers pass `LLMConfig.from_settings(settings)` per invocation
**Apply to:** `AlertService.maybe_send(event, config: AlertConfig)`
**Pattern:**
```python
# In caller (sentinel.process_chunk):
self.alert_service.maybe_send(event, AlertConfig.from_settings(self._settings()))
```
Rationale: Phase 1 established this — settings-derived configs are method-scoped, never ctor-scoped, so they pick up live DB state on every call.

### Pattern S-6: Repositories never commit (Phase 2 D-01 inherited)
**Source:** `app/repositories/analysis_events.py` (every method is query-or-add; no `db.session.commit()` in the whole file)
**Apply to:** `AlertService.maybe_send` — MUST NOT call `db.session.commit()`. Caller (`SentinelService.process_chunk` line 261) commits once after `event.alert_sent`/`event.alert_error` assignment.

### Pattern S-7: `db` always imported from `app.extensions`
**Source:** `app/repositories/analysis_events.py` line 7, `app/services/sentinel.py` line 10, `app/api/prompts.py` line 5, `app/api/telegram.py` (none needed there) — every file uses `from app.extensions import db`
**Apply to:** `app/web/routes.py`, `app/bootstrap.py`, `app/composition.py`
**Anti-pattern to avoid (P-06):** `from app import db` — never appears in any current file; grep PR diff to confirm zero additions.

---

## No Analog Found

None. Every file in this phase has a direct in-repo analog. The only novel shape is `typing.Protocol`, which has precedent in RESEARCH §Code Examples §1 and CLAUDE.md §Alert Strategy Pattern (documented convention even though no existing file uses Protocol yet).

---

## Metadata

**Analog search scope:**
- `/Users/rohan/Downloads/DockSentinel/app/__init__.py` (factory source)
- `/Users/rohan/Downloads/DockSentinel/app/services/` (9 files — all read or grepped)
- `/Users/rohan/Downloads/DockSentinel/app/api/` (8 files — all read or sampled)
- `/Users/rohan/Downloads/DockSentinel/app/repositories/` (6 files)
- `/Users/rohan/Downloads/DockSentinel/app/container.py`
- `/Users/rohan/Downloads/DockSentinel/app/config_objects.py`
- `/Users/rohan/Downloads/DockSentinel/tests/test_sentinel_pipeline.py`

**Files scanned:** ~30
**Pattern extraction date:** 2026-04-14
