---
phase: 04-service-decomposition-and-blueprint
verified: 2026-04-14T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: none
  note: Initial verification
---

# Phase 04: Service Decomposition and Blueprint — Verification Report

**Phase Goal:** Alert logic lives in a dedicated `AlertService` behind an `AlertStrategy` Protocol, web routes live in a Blueprint, and `app/__init__.py` is reduced to pure wiring.
**Verified:** 2026-04-14
**Status:** passed
**Re-verification:** No — initial verification
**Verdict:** PASS

## Goal Achievement

### Observable Truths (ROADMAP Phase 4 Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | AlertService owns alert logic; SentinelService holds no Telegram references and no inline alert gating | VERIFIED | `grep -n 'telegram_notifier\|_send_alert_if_allowed' app/services/sentinel.py` → 0 matches. `SentinelService.__init__` (app/services/sentinel.py:25-40) accepts `alert_service: AlertService`, no `telegram_notifier` parameter. Critical branch at sentinel.py:256-261 delegates: `self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))`. Cooldown check, global rate-limit check, formatting, and dispatch all live in `AlertService.maybe_send` (app/services/alerts.py:51-67). |
| 2 | All web routes registered via a Blueprint — every existing URL pattern and endpoint name works identically | VERIFIED | `app/web/routes.py:11` defines `bp = Blueprint("web", __name__, url_prefix="")`. 11 route handlers with explicit `endpoint=` kwargs. Runtime endpoint map confirms all 11 endpoints present and URLs byte-identical (`/dashboard`, `/settings`, `/exclusions`, `/exclusions/delete/<int:rule_id>`, `/insights`, `/reports`, `/reports/generate`, `/prompts`, `/sentinel/toggle`, `/sentinel/analyze`, `/`). `url_for("dashboard")` resolves to `/dashboard` with no `web.` prefix (confirmed live). Blueprint registered with `name=""` override in app/__init__.py:47. |
| 3 | `app/__init__.py` is under 100 LOC and contains only app factory wiring | VERIFIED | `wc -l app/__init__.py` → **83** (well under 100, and meets tightened D-14 target of ≤90). File contains only 3 functions: `_ensure_sqlite_parent_dir` (16 LOC helper), `_register_blueprints` (17 LOC), `create_app` (34 LOC). No seeding, no route handlers, no service wiring — all extracted to `app/composition.py` and `app/bootstrap.py`. |
| 4 | All 31 existing tests pass unmodified (except the 5-line test-seam swap per CONTEXT D-14) | VERIFIED | `pytest -q` → **31 passed in 3.83s**. `tests/test_sentinel_pipeline.py` contains only the D-14-allowed `_FakeAlertStrategy` class (5 LOC) plus 5 mechanical replacements of `sentinel.telegram_notifier = DummyTelegram()` → `sentinel.alert_service.strategy = _FakeAlertStrategy()`. |

**Score:** 4/4 success criteria verified

### Required Artifacts (3-level verification)

| Artifact | Expected | Exists | Substantive | Wired | Status |
|----------|----------|--------|-------------|-------|--------|
| `app/services/alerts.py` | AlertStrategy Protocol + TelegramAlertStrategy + AlertService | ✓ (76 LOC) | ✓ (3 public classes, full gating pipeline + format + dispatch) | ✓ (imported by `app/composition.py:13`, `app/container.py:12`, `app/services/sentinel.py:21`) | VERIFIED |
| `app/composition.py` | `build_container(app)` assembling full graph | ✓ (83 LOC) | ✓ (dependency-ordered: repos → clients → strategies → services → coordinator) | ✓ (imported inside `create_app`, called at `app/__init__.py:74`) | VERIFIED |
| `app/bootstrap.py` | `seed_defaults()` zero-param seeder | ✓ (36 LOC) | ✓ (seeds SchemaVersion, Settings, SentinelState, ExclusionRules, DEFAULT_PROMPTS; commits) | ✓ (imported inside `create_app`, called at `app/__init__.py:73`) | VERIFIED |
| `app/web/routes.py` | Flask Blueprint with 11 route handlers | ✓ (198 LOC) | ✓ (11 `@bp.route` handlers covering index/dashboard/settings/exclusions/insights/reports/prompts/sentinel; behavior byte-identical to pre-refactor) | ✓ (imported + registered at `app/__init__.py:40,47` with `name=""` override) | VERIFIED |
| `app/web/__init__.py` | Empty package marker | ✓ (0 LOC) | N/A (package marker) | ✓ (enables `app.web.routes` import path) | VERIFIED |
| `app/__init__.py` | ≤100 LOC, factory wiring only | ✓ (83 LOC) | ✓ (3 functions, no seeding/routes/composition inline) | ✓ (entry point for Flask app; `create_app()` consumed by runtime + tests) | VERIFIED |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `SentinelService.process_chunk` | `AlertService.maybe_send` | `self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))` | WIRED | sentinel.py:257-259, return value stored to `event.alert_sent`/`event.alert_error` |
| `AlertService.maybe_send` | `AlertStrategy.send` | `self.strategy.send(message, config)` | WIRED | alerts.py:67, returns tuple |
| `TelegramAlertStrategy.send` | `TelegramNotifier.send_message` | delegated call | WIRED | alerts.py:26-30 |
| `create_app` | `build_container(app)` | function-body local import (P-04 mitigation) | WIRED | __init__.py:72-74 |
| `create_app` | `seed_defaults()` | function-body local import | WIRED | __init__.py:71-73 |
| `_register_blueprints` | `web_bp` | `app.register_blueprint(web_bp, name="")` | WIRED | __init__.py:40,47 — register-time `name=""` override preserves unprefixed endpoints |
| `build_container` | `ServiceContainer` (typed) | returns populated dataclass | WIRED | composition.py:68-83; all 14 fields assigned including new `alert_strategy` + `alert_service` |
| `ServiceContainer.alert_service` / `alert_strategy` | typed fields | dataclass field declarations | WIRED | container.py:25-26 |
| Side-effect model import | SQLAlchemy metadata | `from app import models  # noqa: F401` | WIRED | __init__.py:68 — load-bearing carry-forward from 04-03 deviation fix |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| **SRVC-03** | 04-01-PLAN | AlertService extracted from SentinelService with AlertStrategy protocol | SATISFIED | `AlertStrategy` (Protocol) + `AlertService` classes exist in `app/services/alerts.py`. `AlertService.maybe_send` owns cooldown + rate-limit + format + dispatch pipeline. Runtime import check passes. |
| **SRVC-04** | 04-01-PLAN | TelegramAlertStrategy implements AlertStrategy protocol | SATISFIED | `TelegramAlertStrategy` (alerts.py:19) wraps `TelegramNotifier` and exposes `send(message, config) -> tuple[bool, str \| None]` matching the Protocol. Construction confirmed live. |
| **APP-01** | 04-03-PLAN | Web routes extracted to dedicated Blueprint | SATISFIED | `app/web/routes.py` declares `bp = Blueprint("web", __name__, url_prefix="")` with 11 route handlers. All web routes gone from `app/__init__.py`. |
| **APP-02** | 04-02/04-04 | `app/__init__.py` reduced to ~80 LOC factory wiring | SATISFIED | 83 LOC verified via `wc -l`. 354 → 83 is a −271 LOC delta. Only 3 functions remain, matching CONTEXT D-13. |
| **APP-03** | 04-03-PLAN | All URL patterns + endpoint names preserved | SATISFIED | Runtime check: all 11 expected endpoint names present in `app.url_map`; URLs byte-identical. `url_for("dashboard")` etc. resolve without `web.` prefix via `register_blueprint(web_bp, name="")`. |

All 5 phase requirements closed. REQUIREMENTS.md traceability matrix updated to "Complete" for all five.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | No TODO/FIXME/XXX/HACK/PLACEHOLDER in any created file | — | None |
| — | — | No stub returns, no hardcoded empty lists in UI paths | — | None |

Grep results across `app/services/alerts.py`, `app/composition.py`, `app/bootstrap.py`, `app/web/routes.py`, `app/__init__.py`: **0 matches** for any stub/placeholder pattern.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `pytest -q` — all tests pass | `python -m pytest -q` | **31 passed in 3.83s** | PASS |
| `wc -l app/__init__.py` ≤ 90 | `wc -l app/__init__.py` | **83** | PASS |
| Runtime module imports | `python -c "from app.services.alerts import AlertService, AlertStrategy, TelegramAlertStrategy; ..."` | OK — Protocol flag True, strategy has `send` method | PASS |
| Blueprint endpoint registration | `TESTING=1 python -c "create_app(); check 11 endpoints"` | All 11 endpoints present; 0 missing | PASS |
| `url_for` preserves unprefixed contract | `url_for("dashboard")`, etc. | `/dashboard`, `/settings`, `/exclusions/delete/1`, `/reports/generate` (byte-identical to pre-refactor) | PASS |
| No `from app import db` | `grep -rn 'from app import db' app/` | **0 matches** | PASS |
| No stale factory helpers | `grep -n 'def _seed_defaults\|def _register_web_routes\|def _register_api_blueprints' app/__init__.py` | **0 matches** | PASS |
| No `telegram_notifier` in SentinelService | `grep -n 'telegram_notifier' app/services/sentinel.py` | **0 matches** | PASS |
| ServiceContainer typed fields | `inspect.signature(ServiceContainer)` | 14 fields including `alert_strategy` + `alert_service` | PASS |

### Project-Level Constraints

| Constraint (from PROJECT.md / CLAUDE.md) | Evidence | Status |
|------------------------------------------|----------|--------|
| API contract preserved (all endpoints work, identical shapes) | All 8 API blueprints still registered (`_register_blueprints` at __init__.py:42-44); web endpoint names + URLs byte-identical; `tests/test_ui_routes.py` asserts this and passes | PASS |
| All 31 tests still pass | `pytest -q` → 31 passed. Only 5-line allowed D-14 test-seam swap used. | PASS |
| No new frameworks | `requirements.txt` unchanged from Phase 3 (Flask 3.0.3, SQLAlchemy 2.0.36, Pydantic 2.10.6, pytest 8.3.4, APScheduler 3.10.4, alembic 1.18.4). No new deps added in Phase 4. | PASS |
| No new features | Pure structural refactor. No new routes, no new DB columns, no new behavior. Alert gating logic byte-identical (cooldown + rate limit messages preserved: "duplicate alert suppressed by cooldown", "global rate limit exceeded"). | PASS |
| Incremental delivery | 4 independent plans (04-01 through 04-04), each shipping with 31/31 tests green per SUMMARY | PASS |

## Gaps Summary

**No gaps found.** All four ROADMAP success criteria are met with live-code evidence, all five requirements (SRVC-03, SRVC-04, APP-01, APP-02, APP-03) are satisfied with runtime verification, all project-level constraints hold, and the full test suite passes at 31/31. The SUMMARY's claims reconcile exactly with the codebase — no drift.

Two load-bearing 04-03 deviation fixes are preserved verbatim in `app/__init__.py`:
1. `app.register_blueprint(web_bp, name="")` at line 47 — overrides Flask's default endpoint-prefixing so `url_for("dashboard")` still works unprefixed.
2. `from app import models  # noqa: F401` at line 68 inside the app-context — preserves SQLAlchemy metadata registration needed for TESTING-mode `db.create_all()`.

Both lines are essential and must not be reverted in Phase 5.

## Forward-Carry Items for Phase 5

Carry-forward items for `/gsd:plan-phase` Phase 5:

1. **Do not revert the two load-bearing lines** (`name=""` Blueprint override, side-effect `from app import models` import). These are documented but subtle — Phase 5 refactoring must preserve them.
2. **Pydantic validation (API-01)** — Phase 5 will add Flask-Pydantic to list endpoints. The AlertStrategy Protocol pattern is a good model for transport-agnostic contracts if Phase 5 adds request/response schemas.
3. **Pagination (API-02, API-03)** — `GET /api/insights` and `GET /api/reports` still return unpaginated lists. Add offset/limit/sort params while preserving existing shapes (API-04).
4. **Shared conftest.py (TEST-01)** — each test file currently owns its own `_build_app(tmp_path, monkeypatch)` helper. Centralize in `tests/conftest.py`.
5. **pytest-cov gate (TEST-03)** — baseline coverage should be captured now (before Phase 5 code changes) so the gate threshold is grounded.
6. **Docker hardening (DOCK-01..04)** — non-root user, healthcheck, cache optimization, named volume.
7. **ServiceContainer growth** — 14 fields is approaching the limit of comfortable dataclass sizes. If Phase 5 adds more services, consider grouping (e.g., a `repos` sub-dataclass) — but only if it adds clarity, not churn.
8. **AlertService extensibility** — the Protocol is ready to accept additional strategies (Slack, Discord, Email) without touching SentinelService. Noted for post-milestone roadmap (ROADMAP Phase 3 "SMTP email alerts").

---

_Verified: 2026-04-14_
_Verifier: Claude (gsd-verifier)_
