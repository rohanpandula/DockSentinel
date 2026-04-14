---
phase: 04-service-decomposition-and-blueprint
plan: 03
subsystem: web-blueprint
tags: [refactor, blueprint, web-routes, flask, app-factory]

# Dependency graph
requires:
  - phase: 04-service-decomposition-and-blueprint
    plan: 02
    provides: build_container(app) composition root + seed_defaults() bootstrap; slimmer app/__init__.py with deferred composition imports
provides:
  - app/web/routes.py::bp — Blueprint("web") with 11 route handlers (198 LOC), registered with name="" so endpoints resolve bare
  - app/web/__init__.py — empty package marker
  - app/__init__.py::_register_blueprints — single function registering all 9 blueprints
  - app/__init__.py down to 83 LOC (from 267); _register_web_routes gone
affects: [04-04-app-init-shrink]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Flask Blueprint with register-time name override (app.register_blueprint(bp, name=\"\")) to preserve unprefixed url_for() contracts while still extracting routes from the factory"
    - "Side-effect import of app.models inside create_app() app context to register SQLAlchemy metadata for db.create_all() (replaces implicit registration via deleted top-level imports)"
    - "for-loop blueprint registration (saves ~7 LOC versus 9 individual app.register_blueprint() lines; matches RESEARCH §Code Examples §3)"

key-files:
  created:
    - app/web/__init__.py
    - app/web/routes.py
  modified:
    - app/__init__.py

key-decisions:
  - "web_bp registered with name=\"\" (empty string) at register-time so endpoints resolve without a 'web.' prefix — templates and tests remain byte-identical. Plan locked endpoint= kwargs on @bp.route, but Flask always prepends the Blueprint's own name regardless of endpoint= kwarg; register_blueprint(bp, name=\"\") is the officially-supported override and achieves the plan's must-have truth"
  - "Added 'from app import models  # noqa: F401' inside create_app()'s app-context block to restore SQLAlchemy metadata registration. The plan's step 4 (remove unused top-level imports of ExclusionRule/PromptKey/SentinelState) had the unintended side effect of dropping the implicit model-metadata registration that db.create_all() relies on"
  - "Kept Blueprint name='web' in app/web/routes.py declaration (PATTERNS S-2 locked) and used register-time name='' override instead of trying to construct a Blueprint('', ...) which Flask explicitly rejects"
  - "Registered web_bp LAST in the for-loop group so API blueprints win any URL-shadowing contests (defensive; no actual overlap exists)"

requirements-completed: [APP-01, APP-03]

# Metrics
duration: 6min
completed: 2026-04-14
---

# Phase 04 Plan 03: Web Blueprint extraction (app/web) + factory cleanup

**Extracted all 11 web route handlers from `_register_web_routes` into `app/web/routes.py` as a Flask Blueprint, deleted the inline function, collapsed `_register_api_blueprints` into `_register_blueprints` (now registers 9 blueprints including `web_bp` with `name=""` to preserve unprefixed url_for()), shrinking `app/__init__.py` from 267 to 83 LOC (-184); 31/31 tests green.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-04-14 (worktree session)
- **Completed:** 2026-04-14
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)
- **LOC delta:** `app/__init__.py` 267 → 83 (−184). `app/web/routes.py` +198 new. Net: +14 LOC across factory + web (moved + minor formatting).

## Accomplishments

- New `app/web/__init__.py` (empty package marker, 0 LOC) — follows the shape of `app/repositories/__init__.py` (PATTERNS §`app/web/__init__.py`).
- New `app/web/routes.py` (198 LOC) — `bp = Blueprint("web", __name__, url_prefix="")` with 11 `@bp.route` decorators using explicit `endpoint=` kwargs that match the current function names 1:1 (index, dashboard, settings_page, exclusions_page, exclusions_delete, insights_page, reports_page, reports_generate, prompt_studio_page, sentinel_toggle_from_ui, sentinel_analyze_from_ui). Handler bodies are byte-identical to `_register_web_routes` modulo `app.extensions` → `current_app.extensions` (PATTERNS S-1). Imports are limited to `flask`, `datetime`, and `app.extensions` / `app.models` / `app.time_utils` — no `from app import db` (Pitfall P-06 compliant).
- `app/__init__.py` slimmed from 267 → 83 LOC by:
  - Deleting the 176-LOC `_register_web_routes` function
  - Renaming `_register_api_blueprints` → `_register_blueprints` and adding `from app.web.routes import bp as web_bp` + one `app.register_blueprint(web_bp, name="")` line
  - Collapsing 8 individual `app.register_blueprint(...)` calls into a for-loop over the API blueprints
  - Removing 7 now-unused top-level imports: `datetime`, `redirect`, `render_template`, `request`, `url_for`, `ExclusionRule`, `PromptKey`, `SentinelState`, `utcnow_naive`
- `create_app` now calls `_register_blueprints(app)` exactly once (replacing the previous `_register_api_blueprints` + `_register_web_routes` pair), preserving the startup order `db.init_app → models-import → create_all → seed → build → register → maybe-start-coordinator`.
- 31/31 tests remain green — `tests/test_ui_routes.py::test_ui_routes_smoke` (the APP-03 regression guardrail) verified via both full-suite and direct-path runs.
- Zero template modifications — `git diff --stat HEAD~2 -- app/templates/` is empty. All 12 `url_for()` callers in the 5 templates continue to resolve via their unprefixed names.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create `app/web/__init__.py` and `app/web/routes.py`** — `acc3044` (feat) — Blueprint with 11 handlers.
2. **Task 2: Delete `_register_web_routes`, rename to `_register_blueprints`, register `web_bp`** — `7e4adcc` (refactor) — factory slimmed by 184 LOC; includes the two deviations documented below.

## Files Created/Modified

- `app/web/__init__.py` *(created, 0 LOC)* — empty package marker.
- `app/web/routes.py` *(created, 198 LOC)* — Blueprint `web` with 11 handlers; every decorator uses explicit `endpoint=` kwarg; handler bodies byte-identical to the prior inline version except for `current_app.extensions` substitution.
- `app/__init__.py` *(modified, −184 LOC, 267 → 83)* — dropped `_register_web_routes` and 7 top-level imports; renamed factory blueprint helper; added side-effect `from app import models` import inside the app-context block.

## Decisions Made

- **Register `web_bp` with `name=""` at register-time (not at Blueprint declaration).** During Task 2 verification, the full suite hit `werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'dashboard'. Did you mean 'web.dashboard' instead?` — this revealed that **Flask always prepends the Blueprint's own name to endpoints regardless of the `endpoint=` kwarg on `@bp.route`**; the `endpoint=` kwarg only sets the suffix after the prefix. The plan's locked assumption (and the executor prompt's "critical risk" block) that `endpoint="dashboard"` would suffice was incorrect about Flask's behavior. `Blueprint("", ...)` is rejected at construction (`ValueError: 'name' may not be empty.`), but `app.register_blueprint(bp, name="")` is officially-supported and produces unprefixed endpoints. This preserves every must-have truth: Blueprint name is still `"web"`, `endpoint=` kwargs are still explicit (future-defensive), templates are still untouched, and `url_for("dashboard")` still resolves. Documented as a deviation below.
- **Added side-effect import `from app import models  # noqa: F401` inside the `with app.app_context():` block.** Removing the top-level imports of `ExclusionRule`, `PromptKey`, `SentinelState` (as instructed by the plan's step 4) had the unintended consequence of never loading `app.models.__init__`, which in turn never registered `SchemaVersion` / `Settings` / `AnalysisEvent` / etc. on SQLAlchemy's metadata. `db.create_all()` then ran against empty metadata → no tables created → `tests/test_ui_routes.py::test_ui_routes_smoke` crashed on `SchemaVersion.singleton()` inside `seed_defaults()`. The surgical fix is a single side-effect import immediately before `db.create_all()`. Documented as a deviation below.
- **Preserved the for-loop blueprint registration** with `web_bp` LAST in the sequence. This mirrors the RESEARCH §Code Examples §3 pattern and keeps the API blueprints as defensive winners in any URL-shadowing contest (no actual overlap exists).
- **Kept `_ensure_sqlite_parent_dir` inline** (D-13 lock).
- **No template modifications.** `git diff --stat HEAD~2 -- app/templates/` returns empty (D-11 lock preserved).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocking issue] Blueprint endpoint-prefix behavior required a register-time name override.**
- **Found during:** Task 2 verification (`pytest -q` after rewiring `_register_blueprints`).
- **Issue:** `werkzeug.routing.exceptions.BuildError: Could not build url for endpoint 'dashboard'. Did you mean 'web.dashboard' instead?` on every template render. The plan and executor guardrail both assumed that passing an explicit `endpoint="dashboard"` kwarg on `@bp.route` would produce the endpoint `dashboard` (unprefixed). Flask's actual behavior: `endpoint=` is the suffix; the Blueprint's own name is always prepended. Tested with a minimal Flask reproduction.
- **Fix:** `app.register_blueprint(web_bp, name="")` inside `_register_blueprints`. `Blueprint("", ...)` is rejected at construction with `ValueError: 'name' may not be empty.`, so the override has to happen at register-time. Blueprint declaration in `app/web/routes.py` keeps `name="web"` per PATTERNS S-2 / D-06 / D-09.
- **Files modified:** `app/__init__.py` (one extra call after the for-loop).
- **Commit:** `7e4adcc`.

**2. [Rule 3 — Blocking issue] Missing SQLAlchemy metadata registration after removing top-level model imports.**
- **Found during:** Task 2 verification (direct-path `pytest tests/test_ui_routes.py -x -q` failed with `sqlite3.OperationalError: no such table: schema_version`).
- **Issue:** The plan's step 4 instructed removal of top-level `from app.models import ExclusionRule, PromptKey, SentinelState` from `app/__init__.py`. Those imports were the *only* thing that triggered `app/models/__init__.py` (which imports every model) before `db.create_all()` ran. Without them, `db.create_all()` saw empty metadata and created zero tables, so the next call to `SchemaVersion.singleton()` inside `seed_defaults()` hit an un-created table. Baseline (pre-Task-2) passed because the old top-level imports registered the metadata implicitly.
- **Fix:** `from app import models  # noqa: F401` inside the `with app.app_context():` block, immediately before `db.create_all()`. Zero behavior change in non-TESTING paths (Alembic owns schema there per 03-02); in TESTING mode, restores the implicit metadata registration.
- **Files modified:** `app/__init__.py` (one import line inside the app-context block).
- **Commit:** `7e4adcc`.

No Rule 4 / architectural deviations. Both fixes are surgical — one line each — and preserve every plan must-have truth and every success criterion.

## Verification Results

| Check | Command | Result |
|---|---|---|
| 1. UI routes regression | `pytest tests/test_ui_routes.py -x -q` | 1 passed |
| 2. Full suite | `pytest -q` | 31 passed |
| 3. 11 endpoints registered | `python -c "... app.url_map ..."` | OK — all 11 resolve bare |
| 4. `/dashboard` responds | `client.get('/dashboard')` | 200 |
| 5. No circular `from app import db` | `grep -n 'from app import db' app/web/routes.py app/__init__.py` | 0 matches |
| 6. `_register_web_routes` deleted | `grep -n 'def _register_web_routes' app/__init__.py` | 0 matches |
| 7. 11 `endpoint=` kwargs | `grep -c 'endpoint=' app/web/routes.py` | 11 |
| 8. Zero template modifications | `git diff --stat HEAD~2 -- app/templates/` | empty |
| 9. No unexpected deletions | `git diff --diff-filter=D --name-only HEAD~2 HEAD` | empty |
| 10. No `url_for("web.xxx")` introductions | `grep -rn "url_for(['\"]web\." app/` | 0 matches |

## Issues Encountered

- **Flask Blueprint endpoint-prefix discovery.** The plan and the executor's critical-risk guardrail both held the incorrect belief that `endpoint="dashboard"` on `@bp.route` alone would keep the endpoint unprefixed. It does not — Flask always prepends `Blueprint.name + "."` regardless of the decorator's `endpoint=` kwarg. The fix (`register_blueprint(bp, name="")`) is officially supported and documented in Flask's source. This is worth forwarding to 04-04 / future plans as a durable pattern.
- **Empty-Blueprint-name rejection.** `Blueprint("", __name__)` raises `ValueError: 'name' may not be empty.`. The override must happen at registration time.
- **Direct-path test failure vs. full-suite pass** (transient). Before the `from app import models` fix was applied, the full suite accidentally passed because earlier tests in collection order happened to import `app.models` via their own fixtures, warming SQLAlchemy's metadata. Direct-path invocation (`pytest tests/test_ui_routes.py -x -q`) has no such side effect and crashed on the missing table. The fix makes both invocation modes pass.
- Stray empty `instance/data/docksentinel.db` artifact was created by an ad-hoc `python -c "from app import create_app; create_app()"` debugging call during investigation; deleted after the fix, pre-commit. Not present in any commit.

## Carry-forward for 04-04 (app/__init__.py shrink to ≤90 LOC)

After this plan, `app/__init__.py` stands at **83 LOC** — already under the ≤90 LOC target for 04-04. Candidates that remain in the factory:

- **`_ensure_sqlite_parent_dir`** (16 LOC, lines 13-28) — per D-13 lock, stays inline.
- **`_register_blueprints`** (17 LOC, lines 31-47) — already consolidated via for-loop; minimal further trim.
- **`create_app`** (~32 LOC, lines 50-81) — idiomatic Flask factory shape:
  - Flask() + config assignment (7 lines)
  - `_ensure_sqlite_parent_dir` + `db.init_app` (2 lines)
  - `with app.app_context():` block with metadata import, `db.create_all()` (guarded), `seed_defaults()`, `build_container()` (7 lines)
  - `_register_blueprints(app)` (1 line)
  - Coordinator start gate (4 lines)
- **Imports**: 5 top-level imports — minimally trimmed (`atexit`, `os`, `load_dotenv`, `Flask`, `AppConfig`, `db`).

**04-04 scope** is now largely verification, maybe minor polish (e.g., inlining `_ensure_sqlite_parent_dir` if the team wants — NOT recommended per D-13; could also inline `_register_blueprints` but it's already at 17 LOC and readable). The ≤90 LOC target is met with headroom.

**Important hand-off notes:**
1. The `from app import models  # noqa: F401` side-effect import inside the app-context block is load-bearing for the TESTING path (`db.create_all()`). Do NOT remove in 04-04 without replacing with an equivalent metadata-registration mechanism.
2. `app.register_blueprint(web_bp, name="")` is load-bearing for APP-03 (unprefixed url_for contracts). Do NOT revert to Blueprint-default registration without also migrating all templates to use `web.<endpoint>` — which would violate the phase's "no template modifications" constraint.

## Self-Check: PASSED

Verified during execution:
- `app/web/__init__.py` exists (0 LOC, empty package marker)
- `app/web/routes.py` exists (198 LOC, contains `bp = Blueprint("web"`, 11 `endpoint=` kwargs)
- `app/__init__.py` is 83 LOC, no `_register_web_routes` function, `_register_blueprints` function present
- Both task commits exist in git log: `acc3044` (Blueprint creation), `7e4adcc` (factory rewire + deviation fixes)
- `pytest -q` reports `31 passed`
- `grep -n 'from app import db' app/web/routes.py app/__init__.py` returns 0 matches (Pitfall P-06)
- `grep -c 'endpoint=' app/web/routes.py` returns 11
- `git diff --stat HEAD~2 -- app/templates/` is empty (zero template changes)
- `git diff --diff-filter=D --name-only HEAD~2 HEAD` returns empty (no unintentional deletions)
- No `url_for("web.xxx")` introductions anywhere in code (only mentioned in research docs, which is intentional documentation of the risk)

---
*Phase: 04-service-decomposition-and-blueprint*
*Completed: 2026-04-14*
