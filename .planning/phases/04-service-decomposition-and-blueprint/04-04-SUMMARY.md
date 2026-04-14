---
phase: 04-service-decomposition-and-blueprint
plan: 04
subsystem: app-factory
tags: [refactor, app-factory, verification, acceptance-matrix, human-checkpoint]

# Dependency graph
requires:
  - phase: 04-service-decomposition-and-blueprint
    plan: 03
    provides: app/web/routes.py Blueprint + app/__init__.py at 83 LOC with load-bearing `register_blueprint(web_bp, name="")` and `from app import models` side-effect import
provides:
  - Final audited app/__init__.py (≤90 LOC, exactly 3 functions, clean imports)
  - Phase 4 acceptance matrix evidence (5 requirements + 4 success criteria + 3 negative assertions)
  - Human UI smoke-test checkpoint (pending orchestrator relay to user)
affects: [04-SUMMARY, phase-close]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Audit-only plan: verifies prior plans' output, captures evidence, does not modify code unless regressions are found"
    - "Empty-Blueprint-name registration override (`register_blueprint(bp, name='')`) confirmed load-bearing for APP-03"
    - "Side-effect model import inside app-context confirmed load-bearing for TESTING-mode db.create_all()"

key-files:
  created: []
  modified:
    - .planning/REQUIREMENTS.md

key-decisions:
  - "Task 1 was a verified no-op — app/__init__.py already at 83 LOC after 04-03 and already matching the target shape; no edits required"
  - "Two carry-forward lines from 04-03 deviations preserved as documented: `app.register_blueprint(web_bp, name='')` and `from app import models  # noqa: F401`"
  - "Task 3 (human UI smoke test) deferred to orchestrator — executor does not start the dev server or simulate human approval"
  - "REQUIREMENTS.md traceability updated in this worktree; STATE.md and ROADMAP.md intentionally NOT modified (owned by orchestrator after merge)"

requirements-completed: [APP-02]

# Metrics
duration: 6min
completed: 2026-04-14
---

# Phase 04 Plan 04: Final audit, acceptance matrix, and human checkpoint

**Verified app/__init__.py is already 83 LOC with exactly 3 functions (no-op trim); collected full Phase 4 acceptance evidence — 5/5 requirement closures pass, 4/4 success criteria pass, 3/3 negative assertions hold, 31/31 tests green; Task 3 human UI smoke test deferred to orchestrator for user relay.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-14 (worktree session, post-04-03 wave merge)
- **Completed:** 2026-04-14 (Tasks 1 & 2 only; Task 3 pending human verification)
- **Tasks:** 2 of 3 automated tasks complete; Task 3 is a blocking human checkpoint
- **Files modified:** 1 (`.planning/REQUIREMENTS.md` — traceability updates)
- **Code LOC delta:** 0 (no code changes — audit confirmed prior state)

## Accomplishments

### Task 1 — Final audit + trim of app/__init__.py (no-op pass)

Confirmed that after plans 04-01 / 04-02 / 04-03 the factory already matches the target shape from the plan's `<interfaces>` block. All audit checks passed with zero edits:

- **LOC:** `wc -l app/__init__.py` → **83** (≤ 90 target, well under the Phase 4 success criterion of 100)
- **Functions:** AST parse confirms exactly `{'_ensure_sqlite_parent_dir', '_register_blueprints', 'create_app'}` — no stale helpers (`_seed_defaults`, `_register_web_routes`, `_register_api_blueprints` all absent)
- **Top-level imports:** Exactly 7 items — `from __future__ import annotations`, `atexit`, `os`, `from dotenv import load_dotenv`, `from flask import Flask`, `from app.config import AppConfig`, `from app.extensions import db`. None of the forbidden stale imports remain (`datetime`, `redirect`, `render_template`, `request`, `url_for`, `app.container.ServiceContainer`, `app.models.*`, `app.repositories.*`, `app.services.*`, `app.time_utils.utcnow_naive`)
- **Function-body local imports preserved:** `from app.bootstrap import seed_defaults` and `from app.composition import build_container` are both inside `create_app`'s `with app.app_context():` block (Pitfall P-04 mitigation intact)
- **Blank-line discipline:** PEP-8 compliant — single blank between top-level statements, two blanks between top-level functions
- **Boot-smoke:** `TESTING=1 python -c "from app import create_app; app = create_app()"` returns cleanly with 30 URL-map rules (11 web + 19 API/health/telegram)

**Carry-forward lines preserved per the orchestrator's critical guardrail block** (both introduced as Rule 3 deviations in plan 04-03 and required for correctness):

1. `app.register_blueprint(web_bp, name="")` at line 47 — the empty-string register-time override that prevents Flask from prepending `web.` to Blueprint endpoints; required for unprefixed `url_for("dashboard")` in templates (APP-03 guardrail).
2. `from app import models  # noqa: F401` at line 68 inside `create_app`'s app-context block, before `db.create_all()` — side-effect metadata registration needed for TESTING-mode schema creation after the top-level model imports were removed.

Since the file already matched the plan's locked target shape, **no commit was produced for Task 1** — a no-op audit doesn't carry a code delta. This is documented here as the evidence artifact.

### Task 2 — Phase 4 acceptance matrix (full evidence collection)

All three evidence clusters passed on first run.

**Requirement closure matrix (5/5 pass):**

| Requirement | Evidence command | Result |
|---|---|---|
| SRVC-03 (AlertService + AlertStrategy) | `python -c "from app.services.alerts import AlertService, AlertStrategy; print('OK')"` | **OK** |
| SRVC-04 (TelegramAlertStrategy) | `python -c "from app.services.alerts import TelegramAlertStrategy; from app.services.telegram import TelegramNotifier; t = TelegramAlertStrategy(TelegramNotifier()); print('OK')"` | **OK** |
| APP-01 (web Blueprint) | `python -c "from app.web.routes import bp; assert bp.name == 'web' and bp.url_prefix == ''; print('OK')"` | **OK** |
| APP-02 (≤90 LOC factory) | `wc -l app/__init__.py` | **83** (≤ 90) |
| APP-03 (endpoint names preserved) | `python -c "from app import create_app; rules = {r.endpoint for r in create_app().url_map.iter_rules()}; expected = {11 web endpoints}; assert expected.issubset(rules)"` | **OK** |

**Phase 4 success-criteria matrix (4/4 pass):**

| Criterion | Evidence | Result |
|---|---|---|
| 1. AlertService owns alert logic; SentinelService does not | `grep -n '_send_alert_if_allowed\|self\.telegram_notifier' app/services/sentinel.py` | **0 matches** |
| 2. Web routes via Blueprint, URLs + endpoints identical | `pytest tests/test_ui_routes.py -x -q` | **1 passed** |
| 3. `app/__init__.py` under 100 LOC | `wc -l app/__init__.py` | **83** (tighter than required) |
| 4. All 31 tests pass unmodified | `pytest -q` | **31 passed in 4.42s** |

**Negative assertions (3/3 hold):**

| Assertion | Command | Result |
|---|---|---|
| No `from app import db` anywhere under `app/` | `grep -rn 'from app import db' app/` | **0 matches** |
| No stale factory helpers in `app/__init__.py` | `grep -n 'def _seed_defaults\|def _register_web_routes\|def _register_api_blueprints' app/__init__.py` | **0 matches** |
| `telegram_notifier` gone from sentinel service | `grep -n 'telegram_notifier' app/services/sentinel.py` | **0 matches** |

**Combined `<automated>` verify-block output** (the plan's single-command gate):
```
31 passed in 4.25s
      83 app/__init__.py
ALL ACCEPTANCE CHECKS PASS
```

### Task 3 — Human UI smoke test (pending checkpoint)

Deferred to orchestrator per the non-autonomous plan semantics. The executor does not start the dev server or simulate user approval. The verification script (copied verbatim from the plan's `<how-to-verify>` block) is included below for orchestrator relay.

**Status:** `pending human verification` — awaits "approved" signal from user.

**Verification script (to be relayed by orchestrator):**

1. Start the app:
   ```bash
   flask --app app run --port 5000
   # or: python -m app if an entrypoint exists
   ```
2. Open `http://localhost:5000/` in a browser — should redirect to `/dashboard`.
3. Click through the nav bar (from `app/templates/base.html`):
   - **Dashboard** (`/dashboard`) — renders counts, recent events, latest report, active containers. No 500 error, no "BuildError" about missing endpoints.
   - **Settings** (`/settings`) — renders form. Submit a trivial change (e.g., change `nightly_hour`) — should redirect back to `/settings` with the change persisted.
   - **Exclusions** (`/exclusions`) — renders the exclusion-rule table. Click a "Delete" link (`/exclusions/delete/<rule_id>`) — should redirect back. Add a new pattern via the form — should persist.
   - **Insights** (`/insights`) — renders the filter form + events table. Try `?classification=critical` query param — should work.
   - **Reports** (`/reports`) — renders the report list. Click "Generate" (POSTs to `/reports/generate`) — should redirect back with a new report (may be slow if LLM is configured).
   - **Prompt Studio** (`/prompts`) — renders the prompt list and editor. Save a trivial edit and verify it persists.
4. Dashboard toggle buttons:
   - Click the "Enable Sentinel" / "Disable Sentinel" form buttons (POST `/sentinel/toggle`) — should redirect back with the state flipped.
   - Use the "Analyze container" form (POST `/sentinel/analyze`) with a container name — should redirect back (may no-op silently if container is not running, which is expected behavior).
5. Template sanity:
   - Confirm the Telegram test endpoint at `/api/telegram/test` still works (not a web route but uses the same container).
   - Confirm no JavaScript console errors related to static asset loading (`url_for('static', filename='app.js')`).
6. Watch the server logs — no `werkzeug.routing.exceptions.BuildError`, no `AttributeError: 'ServiceContainer' object has no attribute 'alert_service'`, no `ImportError` on startup.

**Expected outcome:** every page renders identically to v0.2 pre-refactor. If any page shows `BuildError for endpoint '...'` — that's a Pitfall P-03 regression (most likely cause: missing or wrong `endpoint=` kwarg in `app/web/routes.py`). If anything fails, file a bug against plan 04-03 and revise.

**Rollback path:** `git revert` the phase 4 merge commit. The refactor is fully isolated to the modules listed in the plans — no DB migration to roll back.

## Task Commits

- **Task 1:** No commit — audit confirmed `app/__init__.py` already matched the target shape after 04-03. The plan explicitly allows this: *"If `app/__init__.py` is already ≤90 LOC after 04-01/02/03 and matches the target shape, this task is a no-op with a verification pass."*
- **Task 2:** No code commit for the acceptance matrix itself (evidence capture lives in this SUMMARY and the phase roll-up). REQUIREMENTS.md traceability updates are bundled into the final SUMMARY commit.
- **Task 3:** No commit — deferred to human.

Final commit for this plan will include: `04-04-SUMMARY.md`, `04-SUMMARY.md` (phase roll-up), and `REQUIREMENTS.md` (5 requirements marked Complete).

## Files Created/Modified

- `.planning/phases/04-service-decomposition-and-blueprint/04-04-SUMMARY.md` *(created)* — this file
- `.planning/phases/04-service-decomposition-and-blueprint/04-SUMMARY.md` *(created)* — phase-level roll-up (see separate file)
- `.planning/REQUIREMENTS.md` *(modified)* — SRVC-03, SRVC-04, APP-01, APP-02, APP-03 marked `[x]` in v1 list and `Complete` in traceability table; last-updated timestamp bumped to 2026-04-14
- **No code files modified.** `app/__init__.py` is unchanged from 04-03's final commit (`7e4adcc`).

## Decisions Made

- **Task 1 recognized as no-op.** The plan's `<action>` block explicitly accounted for this outcome. Executing a null edit would have produced a noise commit with zero semantic value and risked touching an already-locked file. Documented the LOC and structural assertions as evidence instead.
- **Audit framed as evidence collection, not re-execution.** The acceptance matrix commands are idempotent and read-only; the SUMMARY is the durable artifact.
- **Task 3 not simulated.** Per the non-autonomous plan semantics and the orchestrator's explicit `<non_autonomous_handling>` instruction, the executor does not invoke `flask run` or fabricate human approval. The verification script is relayed verbatim.
- **STATE.md and ROADMAP.md untouched.** The worktree runs under parallel-execution semantics; shared planning files are the orchestrator's responsibility after merge.

## Deviations from Plan

None — plan executed exactly as written. Task 1 was an audit that confirmed the prior state; Task 2's acceptance matrix passed all 12 checks (5 requirements + 4 criteria + 3 negatives) on first run; Task 3 is a blocking checkpoint by design.

## Issues Encountered

- **Worktree base correction.** On agent startup, `git merge-base HEAD` returned the worktree's own HEAD (a divergent commit from a prior phase-0 baseline), not the expected plan-03 merge at `e22be9c`. Resolved with `git reset --hard e22be9c` per the `<worktree_branch_check>` block. All subsequent verification ran against the correct tree.
- **Cosmetic `READ-BEFORE-EDIT` reminders.** Multiple advisory reminders fired during REQUIREMENTS.md edits; the file had been read in the same session at agent startup and all edits succeeded regardless. Not a functional issue.

## Self-Check: PASSED

Verified during execution:
- `app/__init__.py` exists at 83 LOC with exactly 3 functions (`_ensure_sqlite_parent_dir`, `_register_blueprints`, `create_app`) per AST parse
- Both carry-forward lines present at expected positions (line 47 register-override; line 68 side-effect models import)
- `pytest -q` reports `31 passed` (baseline preserved across all 4 Phase 4 plans)
- `TESTING=1 python -c "from app import create_app; app = create_app()"` boots with 30 URL-map rules
- All 5 requirement-closure commands return `OK`
- All 4 success-criteria checks pass
- All 3 negative assertions return 0 matches
- `.planning/REQUIREMENTS.md` shows `[x]` checkboxes for SRVC-03, SRVC-04, APP-01, APP-02, APP-03 and `Complete` in traceability table

---
*Phase: 04-service-decomposition-and-blueprint*
*Completed: 2026-04-14 (Tasks 1 & 2; Task 3 pending human verification)*
