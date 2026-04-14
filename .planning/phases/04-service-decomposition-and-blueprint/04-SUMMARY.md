---
phase: 04-service-decomposition-and-blueprint
type: phase-rollup
subsystems: [services, factory, web-blueprint]
tags: [refactor, service-decomposition, strategy-pattern, composition-root, blueprint, app-factory]

# Dependency graph
requires:
  - phase: 02-repository-layer
    provides: AnalysisEventRepository + commit-free repository pattern
  - phase: 03-config-and-extensions
    provides: AlertConfig dataclass + AppConfig.from_env + shared db extension
provides:
  - app/services/alerts.py — AlertStrategy Protocol + TelegramAlertStrategy + AlertService
  - app/composition.py — build_container(app) dependency-ordered composition root
  - app/bootstrap.py — seed_defaults() zero-param default-data seeder
  - app/web/routes.py — Flask Blueprint with 11 web-UI route handlers
  - app/__init__.py reduced to 83 LOC pure factory wiring (from 354)
affects: [05-api-quality-and-test-infra, future-slack-discord-email-transports, future-react-spa]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Strategy Pattern via typing.Protocol (structural, no abc.ABC)"
    - "Composition-root pattern — dedicated build_container(app) module"
    - "Function-body local imports inside create_app (Pitfall P-04 circular-import mitigation)"
    - "Flask Blueprint with register-time name='' override to preserve unprefixed url_for() contracts"
    - "Side-effect model import inside app-context for TESTING-mode SQLAlchemy metadata registration"

key-files:
  created:
    - app/services/alerts.py (76 LOC)
    - app/composition.py (83 LOC)
    - app/bootstrap.py (36 LOC)
    - app/web/__init__.py (0 LOC)
    - app/web/routes.py (198 LOC)
  modified:
    - app/__init__.py (354 → 83 LOC, -271)
    - app/container.py (+3 LOC)
    - app/services/sentinel.py (+6 / -27)
    - tests/test_sentinel_pipeline.py (+10 / -5)

requirements-completed: [SRVC-03, SRVC-04, APP-01, APP-02, APP-03]

# Metrics
plans-completed: 4
total-duration: ~32min (sum across plans; actual wall-clock with research + waves ~longer)
completed: 2026-04-14
---

# Phase 04 Summary: Service Decomposition & Blueprint Extraction

**Extracted AlertService (Strategy Pattern), lifted composition-root and default-data seeding into dedicated modules, extracted web routes into a Flask Blueprint, and trimmed `app/__init__.py` from 354 to 83 LOC — all while holding the 31-test baseline green across every plan and preserving byte-identical URL contracts.**

## Scope & Intent

Phase 4 was a pure structural refactor with five requirements (SRVC-03, SRVC-04, APP-01, APP-02, APP-03) and four success criteria from ROADMAP.md. No new behavior, no new features, no new dependencies. The goal was to take the already-clean Phase-1-through-3 foundation and complete the service-layer decomposition + give the Flask factory its final canonical shape before Phase 5 (API quality + test infra).

## Plans

| Plan | Title | Duration | Requirements Closed | Key Output |
|---|---|---|---|---|
| 04-01 | AlertService extraction with Protocol-based strategy | ~18 min | SRVC-03, SRVC-04 | `app/services/alerts.py` |
| 04-02 | Composition extraction into app/composition.py + app/bootstrap.py | ~2 min | APP-02 (partial) | `app/composition.py`, `app/bootstrap.py` |
| 04-03 | Web Blueprint extraction (app/web) + factory cleanup | ~6 min | APP-01, APP-03 | `app/web/routes.py` |
| 04-04 | Final audit, acceptance matrix, and human checkpoint | ~6 min | APP-02 (closed) | This SUMMARY + acceptance evidence |

## Plan-by-Plan Highlights

### 04-01 — AlertService extraction

Introduced `AlertStrategy` (typing.Protocol), `TelegramAlertStrategy` (thin wrapper over the existing `TelegramNotifier`), and `AlertService.maybe_send(event, config) -> tuple[bool, str | None]` encapsulating the cooldown + global-rate-limit + format + dispatch pipeline. `SentinelService.__init__` no longer accepts `telegram_notifier` and `_send_alert_if_allowed` was deleted outright. Test seam moved from `sentinel.telegram_notifier` to `sentinel.alert_service.strategy` via a 6-line `_FakeAlertStrategy` + 5 mechanical replacements. Locked error strings (`"duplicate alert suppressed by cooldown"`, `"global rate limit exceeded"`) preserved byte-identically. Commits: `14b065b`, `d953420`, `9fb73a8`.

### 04-02 — Composition root + bootstrap extraction

Created `build_container(app: Flask) -> ServiceContainer` in `app/composition.py` as the single canonical assembly point for the full dependency-ordered graph (repos → clients → strategies → services → coordinator). Created `seed_defaults()` in `app/bootstrap.py` (zero-param, byte-identical body to the old `_seed_defaults`). `create_app` defers to both via function-body local imports — a deliberate mitigation against Pitfall P-04 circular-import risk. `app/__init__.py` shrunk from 354 → 267 LOC (-87). Commits: `e413248`, `6a076f2`.

### 04-03 — Web Blueprint extraction

Created `app/web/routes.py` with `bp = Blueprint("web", __name__, url_prefix="")` and 11 route handlers (index, dashboard, settings_page, exclusions_page, exclusions_delete, insights_page, reports_page, reports_generate, prompt_studio_page, sentinel_toggle_from_ui, sentinel_analyze_from_ui) — each decorated with an explicit `endpoint=` kwarg. `_register_web_routes` deleted; `_register_api_blueprints` renamed to `_register_blueprints`. `app/__init__.py` collapsed from 267 → 83 LOC (-184).

**Two Rule-3 blocking-issue deviations surfaced during verification and were fixed surgically:**
1. Flask always prepends the Blueprint's name to endpoints regardless of `@bp.route(endpoint=...)` — fixed by using the officially-supported register-time override `app.register_blueprint(web_bp, name="")`.
2. Removing the top-level model imports broke SQLAlchemy metadata registration in TESTING mode — fixed by adding `from app import models  # noqa: F401` inside `create_app`'s app-context block, before `db.create_all()`.

Both fixes are load-bearing and documented for carry-forward. Commits: `acc3044`, `7e4adcc`.

### 04-04 — Final audit + acceptance matrix

Task 1 was a verified no-op: `app/__init__.py` already at 83 LOC with the target shape after 04-03. Task 2 collected full acceptance evidence (all 5 requirement closures, all 4 success criteria, all 3 negative assertions pass). Task 3 (human UI smoke test) deferred to orchestrator for user relay. No code changes; `.planning/REQUIREMENTS.md` traceability updated.

## Requirement Closure Evidence (all 5 closed)

| Requirement | Evidence Command | Result |
|---|---|---|
| **SRVC-03** — AlertService + AlertStrategy Protocol | `python -c "from app.services.alerts import AlertService, AlertStrategy; print('OK')"` | **OK** |
| **SRVC-04** — TelegramAlertStrategy implements Protocol | `python -c "from app.services.alerts import TelegramAlertStrategy; from app.services.telegram import TelegramNotifier; t = TelegramAlertStrategy(TelegramNotifier()); print('OK')"` | **OK** |
| **APP-01** — Web Blueprint extracted | `python -c "from app.web.routes import bp; assert bp.name == 'web' and bp.url_prefix == ''; print('OK')"` | **OK** |
| **APP-02** — app/__init__.py pure factory wiring (~80 LOC) | `wc -l app/__init__.py` | **83** (≤90 tightened target; ≤100 Phase 4 criterion) |
| **APP-03** — URL patterns + endpoint names preserved | `TESTING=1 python -c "from app import create_app; rules = {r.endpoint for r in create_app().url_map.iter_rules()}; assert expected.issubset(rules)"` with the 11-element web-endpoint set | **OK** |

## Phase 4 Success Criteria (all 4 met)

| Criterion (from ROADMAP §Phase 4) | Evidence | Status |
|---|---|---|
| 1. AlertService owns alert logic; SentinelService holds no Telegram references and no inline alert gating | `grep -n '_send_alert_if_allowed\|self\.telegram_notifier' app/services/sentinel.py` → 0 matches | **MET** |
| 2. Web routes go through a Blueprint; URLs and endpoint names are identical to pre-refactor baseline | `pytest tests/test_ui_routes.py -x -q` → 1 passed; the test asserts every URL + endpoint name | **MET** |
| 3. `app/__init__.py` is under 100 LOC and contains only app factory wiring (no seeding, no route handlers) | `wc -l app/__init__.py` → 83. AST check → exactly 3 functions: `_ensure_sqlite_parent_dir`, `_register_blueprints`, `create_app` | **MET** |
| 4. All 31 existing tests pass unmodified (a 5-line test-seam swap in `test_sentinel_pipeline.py` is allowed per CONTEXT D-14) | `pytest -q` → 31 passed in 4.42s. The D-14 allowance was used: `_FakeAlertStrategy` class added + 5 mechanical `sentinel.telegram_notifier → sentinel.alert_service.strategy` replacements | **MET** |

## Negative Assertions (all 3 hold)

| Assertion | Command | Result |
|---|---|---|
| No code imports `db` from the `app` package root | `grep -rn 'from app import db' app/` | **0 matches** |
| No stale factory helpers survive in `app/__init__.py` | `grep -n 'def _seed_defaults\|def _register_web_routes\|def _register_api_blueprints' app/__init__.py` | **0 matches** |
| `telegram_notifier` references gone from `SentinelService` | `grep -n 'telegram_notifier' app/services/sentinel.py` | **0 matches** |

## `app/__init__.py` Evolution

| Baseline | After 04-01 | After 04-02 | After 04-03 | After 04-04 |
|---|---|---|---|---|
| 354 LOC | 357 LOC (+3; alert wiring inline) | 267 LOC (−90; composition + bootstrap extracted) | 83 LOC (−184; web Blueprint extracted + 7 imports dropped) | 83 LOC (no change; audit no-op) |

Net phase delta: **−271 LOC** in `app/__init__.py`. The final shape contains only: 7 top-level imports, `_ensure_sqlite_parent_dir` (16 LOC helper), `_register_blueprints` (17 LOC helper), and `create_app` (32 LOC factory) — matching the plan's locked target shape exactly.

## Test Results

- **Baseline (start of phase):** 31 passed
- **End of 04-01:** 31 passed
- **End of 04-02:** 31 passed
- **End of 04-03:** 31 passed
- **End of 04-04:** 31 passed (`pytest -q` latest run: `31 passed in 4.42s`)

No test deleted, no test added, no test xfail'd. The 5-line test-seam swap in `tests/test_sentinel_pipeline.py` (04-01) was the only allowed modification per CONTEXT D-14.

## Files Created / Modified / Deleted Across the Phase

**Created (5 files):**
- `app/services/alerts.py` — 76 LOC (04-01)
- `app/composition.py` — 83 LOC (04-02)
- `app/bootstrap.py` — 36 LOC (04-02)
- `app/web/__init__.py` — 0 LOC (04-03)
- `app/web/routes.py` — 198 LOC (04-03)

**Modified (4 files):**
- `app/__init__.py` — 354 → 83 LOC across 04-01/02/03 (unchanged in 04-04)
- `app/container.py` — +3 LOC (04-01, typed alert attrs)
- `app/services/sentinel.py` — +6 / −27 LOC (04-01, ctor + critical-branch swap, `_send_alert_if_allowed` deleted)
- `tests/test_sentinel_pipeline.py` — +10 / −5 LOC (04-01, `_FakeAlertStrategy` + 5 seam replacements)

**Deleted:** No files. (`_register_web_routes` was a function, not a file — deleted in 04-03.)

## Key Decisions (canonical decisions across the phase)

- **AlertStrategy is `typing.Protocol`**, not `abc.ABC`, and not `@runtime_checkable` — structural duck typing matches the existing service-layer style and avoids forcing `TelegramAlertStrategy` into an inheritance hierarchy.
- **Classification gate stays in SentinelService**, not AlertService — `if verdict.classification == 'critical':` is a domain policy decision; AlertService is transport-agnostic.
- **`telegram_notifier` stays on ServiceContainer** — it's still consumed by `app/api/telegram.py` for the test endpoint. Removing it was explicitly out of scope for 04-01 and would have triggered unnecessary API-surface churn.
- **AlertConfig is constructed per-call via `AlertConfig.from_settings(settings)`**, not stored on AlertService — preserves live-edited-settings behavior (dashboard changes settings between alerts without requiring service reinstantiation).
- **`build_container(app)` takes the Flask app as its only arg** — needed for `RuntimeCoordinator(app=...)`.
- **`seed_defaults()` takes zero parameters** — imports `db` from `app.extensions` for consistency with repository convention (PATTERNS explicit).
- **Function-body local imports in `create_app` for `seed_defaults` and `build_container`** — defers import graph resolution until the `app` package is fully initialized; Pitfall P-04 mitigation.
- **Blueprint registered with `name=""`** (register-time override) — the canonical way to get unprefixed endpoints from a Blueprint whose declaration is `Blueprint("web", ...)`. `Blueprint("", ...)` is rejected at construction.
- **Side-effect `from app import models` inside app-context** — replaces the implicit metadata registration that the removed top-level model imports used to provide. Load-bearing for TESTING-mode `db.create_all()`.

## Carry-forward Decisions for Phase 5

The following decisions are deliberately deferred to Phase 5 and/or beyond — none are regressions, all are documented in ROADMAP / REQUIREMENTS as Pending:

- **Pydantic v2 request/response validation** (API-01) — this phase added no Pydantic models to API routes. Phase 5 will introduce Flask-Pydantic for the list endpoints.
- **Offset/limit pagination** (API-02, API-03) — GET `/api/insights` and GET `/api/reports` still return unpaginated lists. Phase 5 will add `offset`/`limit`/`sort` query params.
- **pytest-cov coverage gate** (TEST-03) — no coverage threshold enforced yet; Phase 5 will configure pytest-cov with 80%+ baseline.
- **Shared `conftest.py` fixture extraction** (TEST-01) — each test file still owns its own app factory + client setup. Phase 5 will centralize.
- **Integration tests for the full sentinel pipeline** (TEST-02) — current tests cover individual stages; Phase 5 will add end-to-end pipeline tests.
- **Docker hardening** (DOCK-01 through DOCK-04) — non-root user, healthcheck, cache optimization, named volume — Phase 5 scope.

## Deviations from Plan (phase-level)

Two small but load-bearing Rule-3 (blocking-issue) deviations surfaced in plan 04-03 verification, both fixed surgically and documented exhaustively in 04-03-SUMMARY.md:

1. **Flask Blueprint endpoint-prefix behavior.** The plan assumed `@bp.route(endpoint="dashboard")` would produce an unprefixed endpoint. Flask actually *always* prepends the Blueprint name. Fix: `app.register_blueprint(web_bp, name="")`. One extra line in `_register_blueprints`.
2. **Missing SQLAlchemy metadata registration.** Removing top-level model imports broke `db.create_all()` in TESTING mode. Fix: `from app import models  # noqa: F401` inside the app-context block. One extra line in `create_app`.

Both lines are explicitly called out in the plan 04-04 orchestrator prompt as "critical carry-forward from 04-03 that must not be reverted." They are preserved in the final `app/__init__.py`.

No Rule 4 (architectural) deviations at any point during the phase. No CONTEXT-locked decisions were violated.

## Threat Flags

None. This phase introduced no new trust boundaries, no new network surface, no new auth paths, no new schema changes. The refactor is structural-only and the security posture is byte-identical to the Phase 3 baseline.

## Known Stubs

None. No hardcoded empty values flowing to UI, no "coming soon" placeholders, no unwired components.

## Outstanding Work (Phase 4)

- **Task 3 human UI smoke test** — pending human verification. The orchestrator should relay the verification script (captured verbatim in 04-04-SUMMARY.md) to the user and collect an "approved" signal before closing the phase.

## Self-Check: PASSED

Verified during execution:
- All 5 phase requirements (SRVC-03, SRVC-04, APP-01, APP-02, APP-03) closed with evidence commands
- All 4 Phase 4 success criteria met (AlertService ownership, Blueprint routing, factory ≤100 LOC, 31/31 tests)
- All 3 negative assertions hold (no `from app import db`, no stale factory helpers, no `telegram_notifier` in sentinel)
- `app/__init__.py` at 83 LOC (271 LOC shrink across the phase)
- All task commits across the 4 plans exist in git log: 04-01 (`14b065b`, `d953420`, `9fb73a8`), 04-02 (`e413248`, `6a076f2`), 04-03 (`acc3044`, `7e4adcc`), 04-04 (final SUMMARY commit pending)
- `pytest -q` reports `31 passed` at the end of every plan
- Two 04-03-deviation carry-forward lines preserved verbatim in `app/__init__.py` (register-time `name=""` override + side-effect models import)

---
*Phase: 04-service-decomposition-and-blueprint*
*Plans: 04-01 → 04-02 → 04-03 → 04-04*
*Completed: 2026-04-14 (Tasks 1 & 2 of 04-04; Task 3 pending human verification)*
