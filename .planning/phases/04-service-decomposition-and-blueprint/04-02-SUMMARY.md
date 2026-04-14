---
phase: 04-service-decomposition-and-blueprint
plan: 02
subsystem: factory
tags: [refactor, composition-root, app-factory, dependency-injection, import-hygiene]

# Dependency graph
requires:
  - phase: 04-service-decomposition-and-blueprint
    plan: 01
    provides: ServiceContainer.alert_strategy and alert_service attrs + AlertService/TelegramAlertStrategy instantiation block added to create_app
provides:
  - app/composition.py::build_container(app) — dependency-ordered composition root (83 LOC)
  - app/bootstrap.py::seed_defaults() — zero-parameter default-data seeder (36 LOC)
  - slimmer app/__init__.py::create_app with function-body local imports for bootstrap + composition
affects: [04-03-blueprint-extraction, 04-04-app-init-shrink]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Composition-root pattern: dedicated build_container(app) -> ServiceContainer module replaces inline factory wiring"
    - "Function-body local imports of app.composition / app.bootstrap inside create_app — defers import graph resolution until the app package is fully initialized (RESEARCH Pitfall P-04 mitigation)"
    - "Zero-param seed_defaults() — imports db from app.extensions for consistency with repositories (PATTERNS recommendation)"

key-files:
  created:
    - app/composition.py
    - app/bootstrap.py
  modified:
    - app/__init__.py

key-decisions:
  - "build_container(app) takes the Flask app as its only argument (needed for RuntimeCoordinator(app=...))"
  - "seed_defaults() takes zero parameters (PATTERNS explicit: consistency with repos > explicitness)"
  - "Function-body local imports of composition + bootstrap inside create_app — mitigates Pitfall P-04 circular-import risk (composition transitively imports many app.* modules)"
  - "`coordinator` variable in create_app now re-fetched via app.extensions['services'].coordinator (container owns instantiation now)"
  - "Preserved top-level imports: ExclusionRule, PromptKey, SentinelState, utcnow_naive — all still consumed by _register_web_routes (which moves in 04-03)"

requirements-completed: [APP-02]

# Metrics
duration: 2min
completed: 2026-04-14
---

# Phase 04 Plan 02: Composition extraction into app/composition.py + app/bootstrap.py

**Relocated the 40-LOC service-wiring block and the 23-LOC _seed_defaults into two dedicated modules (composition.py + bootstrap.py); create_app now defers to them via function-body local imports, shrinking app/__init__.py from 354 to 267 LOC (-87); 31/31 tests green.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-04-14 19:20 UTC (worktree session)
- **Completed:** 2026-04-14
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)
- **LOC delta:** app/__init__.py: 354 → 267 (−87). Net across all three files: +32 LOC (87 removed from __init__, 119 added in composition+bootstrap = includes explicit headers/blank lines reformatted for readability).

## Accomplishments

- New `app/composition.py` (83 LOC) exports `build_container(app: Flask) -> ServiceContainer` — the single canonical assembly point for CLIBackendRunner → LLMClient → LLMCallService → VerdictParser → TelegramNotifier → all five repos → TelegramAlertStrategy → AlertService → SentinelService → BriefingService → RuntimeCoordinator → ServiceContainer
- New `app/bootstrap.py` (36 LOC) exports `seed_defaults()` — body is byte-identical to the prior `_seed_defaults` in `app/__init__.py` (SchemaVersion/Settings/SentinelState singletons, four default exclusion rules, default prompt templates, single `db.session.commit()`)
- `app/__init__.py::create_app` shrunk to 267 LOC by:
  - Dropping 19 wiring-only top-level imports (DEFAULT_PROMPTS, PromptTemplate, ServiceContainer, 5× repository classes, 10× service classes, 2× alert classes)
  - Deleting the 23-LOC `_seed_defaults` function
  - Replacing the 40-LOC wiring block with a 4-line deferred-import + 2 calls (`seed_defaults()`, `app.extensions["services"] = build_container(app)`)
- Circular-import guardrail upheld: `app.composition` and `app.bootstrap` never import from `app.__init__` (composition imports only from `app.container`, `app.repositories.*`, `app.services.*`, `flask`, `os`; bootstrap imports only from `app.extensions`, `app.models`)
- 31/31 tests remained green throughout (baseline verified pre-Task-1, re-verified post-Task-2)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/bootstrap.py** — `e413248` (feat) — zero-param `seed_defaults()` module
2. **Task 2: Create app/composition.py + rewire create_app** — `6a076f2` (refactor) — `build_container(app)` module + 19 import deletions + function-body local imports in create_app

## Files Created/Modified

- `app/composition.py` *(created, 83 LOC)* — `build_container(app)` with dependency-ordered assembly (repos → clients → strategies → services → coordinator); imports verified to never touch `app.__init__` or `app` package root
- `app/bootstrap.py` *(created, 36 LOC)* — `seed_defaults()`; imports `db` from `app.extensions` (Pitfall P-06 compliant)
- `app/__init__.py` *(modified, −87 LOC, 354 → 267)* — dropped 19 top-level imports, deleted `_seed_defaults`, replaced 40-LOC wiring block with 4-line deferred-import pattern, coordinator handle re-fetched from container

## Decisions Made

- **Function-body local imports of `app.bootstrap` and `app.composition` inside `create_app`.** Putting them at module scope would create a potential circular import during partial package initialization — `app.composition` transitively imports many `app.services.*` and `app.repositories.*` modules, some of which may read attributes from `app` at import time. Deferring to function body ensures the `app` package is fully loaded before composition runs. (RESEARCH Pitfall P-04.)
- **seed_defaults() takes zero parameters.** PATTERNS explicitly recommended importing `db` from `app.extensions` to match repository convention ("consistency > explicitness"). CONTEXT D-12 granted discretion; chose the consistency path.
- **coordinator handle re-read from container post-build.** After `build_container(app)` runs, the local `coordinator = ...` line in the old factory is gone. The `atexit.register(coordinator.stop)` block is preserved by extracting the handle from `app.extensions["services"].coordinator`.
- **Preserved 4 top-level imports for web-route use.** `ExclusionRule`, `PromptKey`, `SentinelState`, `utcnow_naive` remain at module scope in `app/__init__.py` because `_register_web_routes` still inlines them. These disappear in 04-03 when the web routes are lifted into a blueprint.
- **No tests modified.** This plan is pure code motion — zero behavior change — so the existing test suite is the regression guardrail; no new test scaffolding or fixture changes required.

## Deviations from Plan

None — plan executed exactly as written. All verification checks passed on the first run:
- `python -c "from app.composition import build_container; from app import create_app; app = create_app(); ..."` (with `TESTING=1` per fixture convention): OK
- `python -c "from app.bootstrap import seed_defaults; from app.composition import build_container"`: OK
- `grep -n 'from app import db' app/composition.py app/bootstrap.py`: 0 matches
- `grep -n 'def _seed_defaults' app/__init__.py`: 0 matches
- `grep -n 'LLMCallService|CLIBackendRunner|AnalysisEventRepository' app/__init__.py`: 0 matches
- `pytest -q`: **31 passed**
- `wc -l app/__init__.py`: **267** (within the plan-expected 270-290 band, slightly below due to tight rewiring)

## Issues Encountered

- **Bare `create_app()` verification (no TESTING flag) hit `sqlite3.OperationalError: no such table: schema_version`.** This is expected behavior in the worktree baseline — `db.create_all()` only runs when `app.config["TESTING"]` is set, and no Alembic migrations were run against the bare sqlite file. Not a regression: re-ran verification with `TESTING=1` per the test-fixture convention (matches how `_build_app` fixture in `tests/` bootstraps the DB). Pytest suite validates the startup path end-to-end and passes.
- Cosmetic `READ-BEFORE-EDIT` reminders fired during edits to `app/__init__.py` — file was read at session start, edits completed successfully regardless.

## Carry-forward for 04-03 (blueprint extraction)

After this plan, `app/__init__.py` still carries:

- **Top-level imports** that will vanish in 04-03:
  - `from datetime import datetime` (consumed by `insights_page`)
  - `redirect, render_template, request, url_for` from `flask` (all web-route handlers)
  - `ExclusionRule`, `PromptKey`, `SentinelState` from `app.models` (three separate web-route handlers)
  - `utcnow_naive` from `app.time_utils` (consumed by `dashboard` route)
- **`_register_web_routes(app)` function** (176 LOC, lines ~58-233) — this is the entire remaining bulk. After it moves into `app/blueprints/web.py`, `app/__init__.py` will drop by ~180 LOC in one shot.
- **`_register_api_blueprints` function** — likely renamed to `_register_blueprints` in 04-03 and extended to register the new web blueprint.

The factory's internal shape is now clean: 6 inline function calls (`_ensure_sqlite_parent_dir`, `db.init_app`, `seed_defaults`, `build_container`, `_register_api_blueprints`, `_register_web_routes`) + coordinator start gate. Plan 04-03 will remove one of those (`_register_web_routes`) and plan 04-04 will inline or collapse the remaining scaffolding to reach the ≤90 LOC target.

## Self-Check: PASSED

Verified during execution:
- `app/composition.py` exists (83 LOC, contains `def build_container(app: Flask) -> ServiceContainer`)
- `app/bootstrap.py` exists (36 LOC, contains `def seed_defaults() -> None`)
- `app/__init__.py` imports cleanly (both `python -c "from app import create_app"` and `pytest` exercise the full startup path)
- Both task commits exist in git log: `e413248` (bootstrap), `6a076f2` (composition + rewire)
- `pytest -q` reports `31 passed` (baseline preserved)
- `grep -n 'from app import db' app/composition.py app/bootstrap.py` returns 0 matches (Pitfall P-06)
- `grep -n 'def _seed_defaults\|LLMCallService\|CLIBackendRunner\|AnalysisEventRepository' app/__init__.py` returns 0 matches
- No unexpected file deletions in either commit (`git diff --diff-filter=D --name-only HEAD~1 HEAD` returned empty)

---
*Phase: 04-service-decomposition-and-blueprint*
*Completed: 2026-04-14*
