---
phase: 05-api-quality-and-hardening
plan: "02"
subsystem: test-infrastructure
tags: [pytest-cov, coverage-gate, integration-tests, schema-parity, pagination]
dependency_graph:
  requires: [05-01]
  provides: [pytest.ini, .coveragerc, tests/conftest.py, tests/test_pipeline_integration.py, tests/test_api_pagination.py, tests/test_api_schemas.py]
  affects: [all test files, CI coverage gate]
tech_stack:
  added: []
  patterns: [shared conftest fixtures, frozen INSIGHT_KEYS/REPORT_KEYS reference sets, LLMResult stub for pipeline integration tests]
key_files:
  created:
    - pytest.ini (updated)
    - .coveragerc
    - tests/conftest.py
    - tests/test_pipeline_integration.py
    - tests/test_api_pagination.py
    - tests/test_api_schemas.py
  modified: []
decisions:
  - "_LLMStub must return LLMResult dataclass (not raw dict) — LLMCallService.call() calls _client.complete() and sentinel.py accesses llm_result.content; raw dicts have no .content attribute"
  - "Pipeline integration test requests db_session fixture to ensure Flask app context is active during process_chunk DB writes (without it, SQLAlchemy session raises RuntimeError: Working outside of application context)"
  - "Sentinel status route is /api/sentinel/status not /api/sentinel — corrected from plan template; parity test asserts sen_body['state'].keys() == SentinelState.as_dict().keys()"
  - "PromptTemplate is the ORM class name in app/models/prompts.py — plan template used 'Prompt' which does not exist; imported as PromptTemplate with alias Prompt"
metrics:
  duration_seconds: 420
  completed_date: "2026-04-14"
  tasks_completed: 2
  files_created: 5
  files_modified: 1
---

# Phase 05 Plan 02: Test Infrastructure + Coverage Gate Summary

**One-liner:** Shared conftest.py fixtures, pytest-cov 80% gate via .coveragerc with scoped omit list, and three new test files (pipeline integration with LLMResult stub, pagination validation, schema parity with frozen key sets) — 46 tests, 90.84% coverage.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | pytest-cov gate, .coveragerc, shared fixtures (conftest.py) | 50d84ba | pytest.ini, .coveragerc, tests/conftest.py |
| 2 | Pipeline integration, pagination, and schema parity tests | dbd8e2f | tests/test_pipeline_integration.py, tests/test_api_pagination.py, tests/test_api_schemas.py |

## Coverage Result

| Scope | Statements | Missed | Coverage |
|-------|-----------|--------|----------|
| app (after omits) | 1256 | 115 | **90.84%** |
| Gate | — | — | 80% (PASSED) |

Notable coverage gains from new tests:
- `app/services/sentinel.py`: 23% → 74% (pipeline integration test exercises process_chunk path)
- `app/services/alerts.py`: 61% → 97%
- `app/repositories/*`: all at 100%
- `app/services/briefing.py`: 37% → 98%

## Test Count

| File | Tests | Purpose |
|------|-------|---------|
| Pre-existing (10 files) | 31 | Unchanged — TEST-04 guard |
| test_pipeline_integration.py | 1 | End-to-end sentinel pipeline (TEST-02) |
| test_api_pagination.py | 8 | Pagination params + error envelope |
| test_api_schemas.py | 6 | Schema field parity, endpoint wire-format parity |
| **Total** | **46** | All pass |

## TEST-04 Diff Guard

```
git status --short tests/ | grep -E '^ M (tests/test_api|tests/test_ui_routes|tests/test_sentinel_pipeline|tests/test_briefing|tests/test_runtime_lock)\.py$'
```
Output: **empty** — no pre-existing test files were modified.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _LLMStub must return LLMResult, not raw dict**
- **Found during:** Task 2, first test run of test_pipeline_integration.py
- **Issue:** The plan's `_LLMStub.chat_completion` returned a raw OpenAI-shaped dict. `LLMCallService.call()` returns whatever `_client.complete()` returns, and `sentinel.py` line 237 accesses `llm_result.content`. A dict has no `.content` attribute — `AttributeError: 'dict' object has no attribute 'content'`.
- **Fix:** Rewrote `_LLMStub` to return `LLMResult(content=..., model="stub", latency_ms=1, usage={})` from both `complete()` and `chat_completion()`. Matches what `DummyLLM` in `test_sentinel_pipeline.py` does.
- **Files modified:** tests/test_pipeline_integration.py
- **Commit:** dbd8e2f

**2. [Rule 1 - Bug] Pipeline test needs app context for DB writes**
- **Found during:** Task 2, first test run of test_pipeline_integration.py
- **Issue:** `container` fixture accesses `app.extensions["services"]` but does not push an app context. `sentinel.process_chunk()` calls SQLAlchemy session operations which require an active app context. `RuntimeError: Working outside of application context.`
- **Fix:** Added `db_session` as a parameter to `test_full_sentinel_pipeline_persists_event_and_exposes_via_api`. The `db_session` fixture wraps its body in `with app.app_context()`, providing the needed context for the duration of the test.
- **Files modified:** tests/test_pipeline_integration.py
- **Commit:** dbd8e2f

**3. [Rule 1 - Bug] Sentinel status route is /api/sentinel/status, not /api/sentinel**
- **Found during:** Task 2, reviewing app/api/sentinel.py
- **Issue:** The plan's test template used `client.get("/api/sentinel")` but the Blueprint registers `/api/sentinel/status`. No route at `/api/sentinel` — would return 404.
- **Fix:** Changed to `client.get("/api/sentinel/status")` and updated the assertion comment accordingly.
- **Files modified:** tests/test_api_schemas.py
- **Commit:** dbd8e2f

**4. [Rule 1 - Bug] PromptTemplate is the ORM class, not Prompt**
- **Found during:** Task 2, first test run of test_api_schemas.py
- **Issue:** Plan template imported `from app.models.prompts import Prompt`. The actual class is `PromptTemplate`. `ImportError: cannot import name 'Prompt' from 'app.models.prompts'`.
- **Fix:** Changed import to `from app.models.prompts import PromptTemplate as Prompt`.
- **Files modified:** tests/test_api_schemas.py
- **Commit:** dbd8e2f

## Known Stubs

None — all test stubs are test infrastructure (LLMResult stub, FakeAlertStrategy), not production code placeholders.

## Threat Flags

None — this plan adds only test files and configuration; no new network endpoints, auth paths, or schema changes.

## Self-Check

### Created files exist
- pytest.ini: FOUND (updated)
- .coveragerc: FOUND
- tests/conftest.py: FOUND
- tests/test_pipeline_integration.py: FOUND
- tests/test_api_pagination.py: FOUND
- tests/test_api_schemas.py: FOUND

### Commits exist
- 50d84ba: Task 1 — pytest.ini, .coveragerc, conftest.py
- dbd8e2f: Task 2 — three test files

## Self-Check: PASSED
