---
phase: 02-repository-layer
plan: 02
subsystem: services
tags: [repository-pattern, dependency-injection, sentinel, briefing, sqlalchemy]

requires:
  - phase: 02-repository-layer
    plan: 01
    provides: Five repository classes (AnalysisEventRepository, ExclusionRepository, PromptRepository, ReportRepository, SettingsRepository) wired into create_app()

provides:
  - SentinelService with constructor-injected event_repo, prompt_repo, exclusion_repo
  - BriefingService with constructor-injected event_repo, prompt_repo, report_repo
  - Zero inline ORM query calls in sentinel.py or briefing.py
  - create_app() passes repos to both service constructors

affects: [02-03, sentinel-pipeline, briefing-generation]

tech-stack:
  added: []
  patterns:
    - Constructor injection of repository instances into service classes
    - TYPE_CHECKING guard for forward references to repository types
    - Services retain db.session.commit() ownership (repos never commit per D-01)
    - ExclusionRule accessed only via exclusion_repo.list_enabled() — no direct import into sentinel

key-files:
  created: []
  modified:
    - app/services/sentinel.py
    - app/services/briefing.py
    - app/__init__.py

decisions:
  - SentinelService constructor updated to accept 6 parameters (3 existing + 3 new repos); backward compat not needed since only create_app() instantiates it
  - PromptTemplate import retained in briefing.py for return type annotation on _prompt()
  - db import retained in briefing.py since db.session.commit() remains the service's responsibility per D-01

metrics:
  duration: 17
  completed: "2026-04-05"
  tasks: 2
  files_changed: 3
---

# Phase 02 Plan 02: Service Repository Injection Summary

**One-liner:** Constructor injection of repository instances into SentinelService and BriefingService, replacing all inline SQLAlchemy queries in both service files.

## What Was Built

Both heavy-query service files had their direct ORM calls replaced with injected repository method calls.

**SentinelService changes (app/services/sentinel.py):**
- Constructor now accepts `event_repo`, `prompt_repo`, `exclusion_repo` in addition to existing 3 args
- `is_excluded_container()`: replaced `ExclusionRule.query.filter_by(enabled=True).all()` with `self.exclusion_repo.list_enabled()`
- `_prompt()`: replaced `PromptTemplate.query.filter_by(key=key.value).first()` with `self.prompt_repo.get_by_key(key)`
- `_record_excluded_event()`: replaced inline `AnalysisEvent.query.filter(...)` with `self.event_repo.find_recent_excluded()` and `self.event_repo.add()`
- `process_chunk()`: replaced 3 inline `AnalysisEvent.query.filter(...)` calls with `event_repo.find_duplicate_chunk()`, `event_repo.count_recent_by_container()`, and `event_repo.add()`
- `_send_alert_if_allowed()`: replaced 2 inline `AnalysisEvent.query.filter(...)` calls with `event_repo.find_alert_duplicate()` and `event_repo.count_recent_alerts()`
- Removed `from sqlalchemy import and_` import (no longer needed)
- Removed inline `from app.models import ExclusionRule` import inside `is_excluded_container()`

**BriefingService changes (app/services/briefing.py):**
- Constructor now accepts `event_repo`, `prompt_repo`, `report_repo` in addition to `llm_call_service`
- `_prompt()`: replaced `PromptTemplate.query.filter_by(key=key.value).first()` with `self.prompt_repo.get_by_key(key)`
- `generate_report()`: replaced `AnalysisEvent.query.filter(...).order_by(...).all()` with `self.event_repo.get_for_window()`
- `generate_report()`: replaced `db.session.add(report)` with `self.report_repo.add(report)` (kept `db.session.commit()`)

**app/__init__.py changes:**
- `SentinelService(...)` call updated to pass `event_repo=event_repo`, `prompt_repo=prompt_repo`, `exclusion_repo=exclusion_repo`
- `BriefingService(...)` call updated to pass `event_repo=event_repo`, `prompt_repo=prompt_repo`, `report_repo=report_repo`

## Verification

```
python -m pytest tests/ -x -q → 31 passed
grep -n "\.query\." app/services/sentinel.py → (no matches)
grep -n "\.query\." app/services/briefing.py → (no matches)
grep -n "db\.session\.add" app/services/sentinel.py → (no matches)
grep -n "db\.session\.add" app/services/briefing.py → (no matches)
```

Only `db.session.commit()` calls remain in both service files, per D-01.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. Both services are fully wired to live repository instances.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1: SentinelService repo injection | ecb0b6c | feat(02-02): migrate SentinelService to injected repositories |
| Task 2: BriefingService repo injection | 070d52f | feat(02-02): migrate BriefingService to injected repositories |

## Self-Check: PASSED

- app/services/sentinel.py: exists, contains `self.event_repo = event_repo`, `self.prompt_repo = prompt_repo`, `self.exclusion_repo = exclusion_repo`
- app/services/briefing.py: exists, contains `self.event_repo = event_repo`, `self.prompt_repo = prompt_repo`, `self.report_repo = report_repo`
- app/__init__.py: contains `SentinelService(` with `event_repo=event_repo` and `BriefingService(` with `event_repo=event_repo`
- Commits ecb0b6c and 070d52f exist in git log
- All 31 tests pass
