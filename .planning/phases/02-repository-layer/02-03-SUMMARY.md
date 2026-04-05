---
phase: 02-repository-layer
plan: 03
subsystem: api-routes
tags: [repository-pattern, api, web-routes, refactor]
dependency_graph:
  requires: [02-01]
  provides: [REPO-02, REPO-03-api]
  affects: [app/api, app/__init__.py]
tech_stack:
  added: []
  patterns: [repository-pattern, dependency-injection, container-access]
key_files:
  created: []
  modified:
    - app/api/exclusions.py
    - app/api/prompts.py
    - app/api/reports.py
    - app/api/settings.py
    - app/api/insights.py
    - app/__init__.py
decisions:
  - "Web routes use app.extensions['services'] (not current_app) because closures capture app via outer scope"
  - "db.session.commit() retained in exclusions/prompts route handlers — repositories own queries, callers own transaction boundaries per D-01"
  - "AnalysisEvent and DailyReport removed from __init__.py model imports — only used in routes now removed to repo calls; ExclusionRule/PromptTemplate/PromptKey kept for _seed_defaults()"
  - "insights_page uses svc alias to avoid shadowing request.args.get('container') local variable"
metrics:
  duration: 15
  completed_date: "2026-04-05"
  tasks: 2
  files_modified: 6
---

# Phase 02 Plan 03: Route Handler Repository Migration Summary

All API and web route handlers migrated from inline SQLAlchemy ORM queries to repository method calls via the ServiceContainer — zero inline `.query.` calls in `app/api/` with all 31 tests passing.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Migrate API route handlers to use repos from container | beae42c | app/api/exclusions.py, prompts.py, reports.py, settings.py, insights.py |
| 2 | Migrate web route handlers in app/__init__.py to use repos | 4197b79 | app/__init__.py |

## What Changed

### Task 1: API Blueprints (5 files)

**app/api/exclusions.py:** `ExclusionRule.query.order_by()`, `ExclusionRule.query.filter_by()`, `db.session.get(ExclusionRule)`, `db.session.add()`, `db.session.delete()` replaced with `container.exclusion_repo.list_all()`, `.find_by_pattern()`, `.get()`, `.add()`, `.delete()`. `db.session.commit()` retained (transaction boundary, not query).

**app/api/prompts.py:** `PromptTemplate.query.order_by()`, `PromptTemplate.query.filter_by()` × 2 replaced with `container.prompt_repo.list_all()`, `.get_by_key()`. Removed `from app.models import PromptTemplate` (no longer constructing templates in this file).

**app/api/reports.py:** `DailyReport.query.order_by()`, `db.session.get(DailyReport)` replaced with `container.report_repo.list_all()`, `.get()`. Removed `from app.extensions import db` and `from app.models import DailyReport` — no longer needed.

**app/api/settings.py:** `Settings.singleton()` × 3 replaced with `container.settings_repo.get()`. `db.session.commit()` replaced with `container.settings_repo.save()`. Removed `from app.extensions import db` and `from app.models import Settings`.

**app/api/insights.py:** Inline chained query replaced with `container.event_repo.get_filtered(container=, classification=, start=, end=, limit=)`. Removed `from app.models import AnalysisEvent`.

### Task 2: Web Routes in app/__init__.py

**dashboard():** 3 inline queries → `container.event_repo.get_today()`, `.get_recent()`, `container.report_repo.get_latest()`.

**settings_page():** `Settings.singleton()` → `container.settings_repo.get()`. `db.session.commit()` → `container.settings_repo.save()`.

**exclusions_page():** `ExclusionRule.query.filter_by()` + `db.session.add()` → `container.exclusion_repo.find_by_pattern()` + `.add()`. `ExclusionRule.query.order_by()` → `.list_all()`.

**exclusions_delete():** `db.session.get(ExclusionRule)` + `db.session.delete()` → `container.exclusion_repo.get()` + `.delete()`.

**insights_page():** Inline chained query + `db.session.query(...).distinct()` → `svc.event_repo.get_filtered()` + `.get_distinct_container_names()`.

**reports_page():** `DailyReport.query.order_by()` + `db.session.get(DailyReport)` → `container.report_repo.list_all()` + `.get()`.

**prompt_studio_page():** `PromptTemplate.query.filter_by()` × 2 + `PromptTemplate.query.order_by()` → `container.prompt_repo.get_by_key()` × 2 + `.list_all()`.

**Model imports cleaned up:** `AnalysisEvent` and `DailyReport` removed from `app/__init__.py` module-level imports — neither is needed in routes or infrastructure code anymore.

## Verification

```
grep -rn "\.query\." app/api/  # exit 1 (no matches) — PASSED
pytest tests/ -x -q            # 31 passed — PASSED
```

REPO-03 scope for this plan (api routes + web routes): satisfied. Services (`sentinel.py`, `briefing.py`) addressed by plan 02-02.

## Deviations from Plan

None — plan executed exactly as written. The plan's code snippets were used directly with one minor naming deviation: `insights_page` uses `svc` alias for the container variable to avoid shadowing the `container` query parameter from `request.args.get("container")`, which is consistent with the plan's intent.

## Known Stubs

None. All route handlers wire real repository data.

## Self-Check: PASSED

- app/api/exclusions.py: exists, contains `container.exclusion_repo.list_all()` ✓
- app/api/prompts.py: exists, contains `container.prompt_repo.get_by_key(` ✓
- app/api/reports.py: exists, contains `container.report_repo.list_all()` ✓
- app/api/settings.py: exists, contains `container.settings_repo.get()` ✓
- app/api/insights.py: exists, contains `container.event_repo.get_filtered(` ✓
- app/__init__.py: contains `container.event_repo.get_today(`, `container.report_repo.get_latest()`, `container.settings_repo.save()` ✓
- Commits beae42c and 4197b79 exist ✓
- 31 tests pass ✓
