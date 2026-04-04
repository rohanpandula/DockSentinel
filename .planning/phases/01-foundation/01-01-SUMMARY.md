---
phase: 01-foundation
plan: "01"
subsystem: services
tags: [refactor, llm, extraction, dry]
dependency_graph:
  requires: []
  provides: [LLMCallService, llm_call_service injection]
  affects: [sentinel.py, briefing.py, api/settings.py, app/__init__.py]
tech_stack:
  added: []
  patterns: [service extraction, constructor injection]
key_files:
  created:
    - app/services/llm_call.py
  modified:
    - app/services/sentinel.py
    - app/services/briefing.py
    - app/api/settings.py
    - app/__init__.py
    - tests/test_sentinel_pipeline.py
    - tests/test_briefing.py
    - tests/test_api.py
decisions:
  - temperature=None omits the kwarg so LLMClient uses its default (0.1) rather than passing None
  - test-connection endpoint hardcodes max_retries=0 and cli_max_retries=0 (not from settings) to match original behavior
  - ServiceContainer.llm_call field populated with LLMCallService instance (was None placeholder from parallel agent 01-02)
metrics:
  duration_seconds: 180
  completed_date: "2026-04-04"
  tasks_completed: 2
  files_changed: 7
---

# Phase 01 Plan 01: Extract LLMCallService Summary

Extracted ~120 LOC of triplicated LLM invocation logic from sentinel.py, briefing.py, and api/settings.py into a single LLMCallService class in app/services/llm_call.py.

## What Was Built

Single `LLMCallService.call()` method handles all three LLM invocation variants (sentinel analysis, nightly briefing at temperature=0.2, test-connection at temperature=0.0 with retries=0). Transport switching (API vs CLI timeout/retry resolution) now lives in exactly one place.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Create LLMCallService | 76877f0 | app/services/llm_call.py |
| 2 | Wire into sentinel, briefing, settings, update tests | bc82093 | 7 files |

## Decisions Made

1. `temperature=None` means "omit from kwargs" — preserves LLMClient.complete() default of 0.1 without explicitly passing it.
2. `test-connection` endpoint hardcodes `max_retries=0` and `cli_max_retries=0` — both from original behavior, not from settings.
3. `ServiceContainer.llm_call` field (introduced by parallel agent 01-02) is now populated with the LLMCallService instance instead of the `None` placeholder.

## Verification

- `grep -rn "_call_llm" app/ tests/` returns zero results
- `LLMCallService` imported and used in: llm_call.py (definition), sentinel.py, briefing.py, __init__.py
- All 31 tests pass (3.70s)

## Deviations from Plan

### Adaptation: ServiceContainer integration

**Found during:** Task 2

**Issue:** A parallel agent (01-02) had already modified `app/__init__.py` to use a `ServiceContainer` dataclass instead of the raw `app.extensions["services"]` dict. The plan referenced the dict pattern.

**Fix:** Followed the newer pattern — added `llm_call=llm_call_service` to `ServiceContainer` constructor (replacing the `None` placeholder left by the parallel agent). Updated all attribute accesses consistently.

**Files modified:** app/__init__.py, app/api/settings.py, tests/test_api.py, tests/test_sentinel_pipeline.py, tests/test_briefing.py

**Commit:** bc82093

## Known Stubs

None — all LLMCallService wiring is fully connected.

## Self-Check: PASSED
