---
phase: 05-api-quality-and-hardening
plan: "01"
subsystem: api
tags: [pydantic, flask-pydantic, pagination, validation, schemas]
dependency_graph:
  requires: []
  provides: [app/schemas/, app/errors.py, offset-pagination on insights+reports]
  affects: [app/api/*, app/repositories/analysis_events.py, app/repositories/reports.py]
tech_stack:
  added: [Flask-Pydantic==0.14.0, pytest-cov==7.1.0]
  patterns: [Pydantic v2 from_attributes schemas, @validate decorator, error envelope remap]
key_files:
  created:
    - app/schemas/__init__.py
    - app/schemas/common.py
    - app/schemas/insights.py
    - app/schemas/reports.py
    - app/schemas/exclusions.py
    - app/schemas/prompts.py
    - app/schemas/sentinel.py
    - app/schemas/settings.py
    - app/schemas/telegram.py
    - app/schemas/health.py
    - app/errors.py
  modified:
    - requirements.txt
    - app/__init__.py
    - app/api/insights.py
    - app/api/reports.py
    - app/api/exclusions.py
    - app/api/prompts.py
    - app/api/sentinel.py
    - app/api/settings.py
    - app/api/telegram.py
    - app/api/health.py
    - app/repositories/analysis_events.py
    - app/repositories/reports.py
decisions:
  - "Drop from __future__ import annotations from @validate-decorated route files — Flask-Pydantic 0.14.0 reads func.__annotations__ directly; PEP 563 lazy strings make issubclass() fail at runtime (TypeError: issubclass() arg 1 must be a class)"
  - "Use Variant A (@validate decorator with explicit body=/query= kwargs) on all mutation endpoints — avoids annotation-inference ambiguity"
  - "SettingsSchema uses from_attributes=True with model_validate(settings_orm_row); GET /api/settings returns model_dump() which preserves all 27 as_dict field names byte-for-byte"
  - "SentinelStateSchema mirrors SentinelState.as_dict exactly (7 fields: enabled, runtime_status, started_at, last_error, llm_failure_count, llm_last_failure_at, updated_at) — the plan interface section listed incorrect field names (last_started_at, last_stopped_at) which were corrected by reading the model source"
metrics:
  duration_seconds: 304
  completed_date: "2026-04-14"
  tasks_completed: 2
  files_created: 11
  files_modified: 12
---

# Phase 05 Plan 01: Pydantic v2 API Schemas + Flask-Pydantic Wiring Summary

**One-liner:** Pydantic v2 request/response schemas across all 8 API blueprints with Flask-Pydantic @validate, offset/limit/sort pagination on /api/insights and /api/reports, and a ValidationError-to-{"error":...} envelope remap in app/errors.py.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create app/schemas/ package and request+response models | de754c9 | app/schemas/ (10 files), requirements.txt |
| 2 | Wire Flask-Pydantic response validation + pagination + error handler | 960f08c | app/errors.py, app/__init__.py, app/api/* (8 files), app/repositories/* (2 files) |

## Schema Field Parity Against as_dict()

| Schema | Fields | Source as_dict() | Parity |
|--------|--------|-----------------|--------|
| InsightItem | 22 | AnalysisEvent.as_dict() | exact |
| ReportItem / ReportDetailResponse | 9 | DailyReport.as_dict() | exact |
| ExclusionRuleSchema | 5 | ExclusionRule.as_dict() | exact |
| PromptSchema | 7 | PromptTemplate.as_dict() | exact |
| SentinelStateSchema | 7 | SentinelState.as_dict() | exact |
| SettingsSchema | 27 | Settings.as_dict() | exact |
| TelegramTestResponse | 2 | inline jsonify shape | exact |
| HealthResponse | 2 | inline jsonify shape | exact |

## @validate Pattern Chosen Per Endpoint

| Endpoint | Variant | Notes |
|----------|---------|-------|
| GET /api/insights | Variant A — `@validate(query=InsightsQuery)` | Returns `InsightListResponse(...)` directly (Flask-Pydantic serializes BaseModel returns) |
| GET /api/reports | Variant A — `@validate(query=ReportsQuery)` | Returns `ReportListResponse(...)` directly |
| POST /api/exclusions | `@validate(body=CreateExclusionBody)` | Returns `.model_dump(), 201` |
| PUT /api/prompts/<key> | `@validate(body=UpdatePromptBody)` | Returns `.model_dump(), 200` |
| POST /api/sentinel/toggle | `@validate(body=ToggleBody)` | None-flip logic preserved in handler |
| POST /api/sentinel/analyze-now | `@validate(body=AnalyzeBody)` | Returns AnalyzeResponse.model_dump() |
| PUT /api/settings | `@validate(body=UpdateSettingsBody)` | `exclude_unset=True` preserves partial-update semantics |
| GET /api/settings | no decorator | Returns SettingsSchema.model_validate(row).model_dump() |
| GET/POST health, telegram, other GETs | no decorator | Returns Model.model_dump() inline |

## Datetime Serialization Observation (Pitfall P-01)

Pydantic v2 `model_dump()` serializes `datetime` fields as Python `datetime` objects by default — NOT as ISO 8601 strings. Flask's `jsonify()` handles the conversion via its JSON encoder, which calls `.isoformat()`. This means the wire output is **functionally identical** to the previous `as_dict()` approach (which called `.isoformat()` explicitly). No microsecond trimming or timezone drift was observed — all test assertions on datetime fields passed without modification.

When returning `Model(...)` directly from a `@validate`-decorated route (Flask-Pydantic path), Flask-Pydantic calls `model.model_dump_json()` before setting the response body. This also produces ISO 8601 strings for datetime fields. The two paths produce identical wire format.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed `from __future__ import annotations` from @validate-decorated route files**
- **Found during:** Task 2, first test run
- **Issue:** Flask-Pydantic 0.14.0 reads `func.__annotations__` directly (line 220-221 of core.py). With PEP 563 lazy evaluation (`from __future__ import annotations`), all annotations become strings. `issubclass('UpdateSettingsBody', V1BaseModel)` raises `TypeError: issubclass() arg 1 must be a class`. This is Pitfall P-07 from the research.
- **Fix:** Removed `from __future__ import annotations` from the six route files that use `@validate`: insights.py, reports.py, exclusions.py, prompts.py, sentinel.py, settings.py. Files without `@validate` (telegram.py, health.py) were left with their existing import style.
- **Files modified:** app/api/insights.py, app/api/reports.py, app/api/exclusions.py, app/api/prompts.py, app/api/sentinel.py, app/api/settings.py
- **Commit:** 960f08c

**2. [Rule 1 - Bug] Corrected SentinelStateSchema field list**
- **Found during:** Task 1, reading app/models/sentinel_state.py
- **Issue:** The plan's `<interfaces>` section listed `last_started_at`, `last_stopped_at` as SentinelState fields. The actual model has `runtime_status`, `started_at`, `last_error`, `llm_failure_count`, `llm_last_failure_at` — different names and additional fields.
- **Fix:** SentinelStateSchema mirrors the actual `SentinelState.as_dict()` method (7 fields) exactly, not the plan's field list.
- **Files modified:** app/schemas/sentinel.py
- **Commit:** de754c9

## Self-Check

### Created files exist
- app/schemas/__init__.py: FOUND
- app/schemas/common.py: FOUND
- app/schemas/insights.py: FOUND
- app/schemas/reports.py: FOUND
- app/schemas/exclusions.py: FOUND
- app/schemas/prompts.py: FOUND
- app/schemas/sentinel.py: FOUND
- app/schemas/settings.py: FOUND
- app/schemas/telegram.py: FOUND
- app/schemas/health.py: FOUND
- app/errors.py: FOUND

### Commits exist
- de754c9: FOUND
- 960f08c: FOUND

## Self-Check: PASSED
