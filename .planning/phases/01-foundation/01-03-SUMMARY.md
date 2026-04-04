---
phase: 01-foundation
plan: 03
subsystem: config-decomposition
tags: [config-objects, frozen-dataclasses, llm-config, refactoring, type-safety]
dependency_graph:
  requires: [01-01-LLMCallService, 01-02-ServiceContainer]
  provides: [LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig]
  affects: [app/services/llm_call.py, app/services/sentinel.py, app/services/briefing.py, app/api/settings.py]
tech_stack:
  added: []
  patterns: [frozen-dataclass-value-object, from_settings-factory-classmethod, TYPE_CHECKING-guard]
key_files:
  created:
    - app/config_objects.py
  modified:
    - app/services/llm_call.py
    - app/services/sentinel.py
    - app/services/briefing.py
    - app/api/settings.py
decisions:
  - "TYPE_CHECKING guard on Settings import in config_objects.py prevents circular import — Settings must not import config_objects at runtime"
  - "LLMConfig.from_settings normalizes transport via (or 'api').strip().lower() — normalization centralized in factory, not spread across call sites"
  - "test-connection endpoint uses dataclasses.replace to override max_retries=0, cli_max_retries=0, preserving original zero-retries behavior"
  - "max_tokens and temperature remain explicit call() params (call-specific), not part of LLMConfig (config-level settings)"
metrics:
  duration: "~4 minutes"
  completed: "2026-04-04T23:29:44Z"
  tasks_completed: 2
  files_changed: 5
---

# Phase 01 Plan 03: Config Decomposition Summary

**One-liner:** Five frozen config dataclasses (LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig) decompose the Settings god object, and LLMCallService.call() now accepts LLMConfig instead of 10 individual LLM kwargs.

## What Was Built

`app/config_objects.py` — five `@dataclass(frozen=True)` value objects, each with a `from_settings(s: Settings)` classmethod. A `TYPE_CHECKING` guard prevents any runtime circular import with the Settings ORM model. `LLMConfig.from_settings` centralizes the `(s.llm_transport or "api").strip().lower()` normalization that was previously duplicated at every call site.

`app/services/llm_call.py` — `LLMCallService.call()` signature reduced from 12 kwargs to 4 (`config: LLMConfig`, `messages`, `max_tokens`, `temperature`). Body reads all LLM connection params from `config.*` fields.

`app/services/sentinel.py` — `process_chunk` call site updated: constructs `LLMConfig.from_settings(settings)` inline, passing the config object to `llm_call_service.call()`.

`app/services/briefing.py` — `generate_report` call site updated identically, with `temperature=0.2` preserved as explicit param.

`app/api/settings.py` — `test_llm_connection` uses `dataclasses.replace(LLMConfig.from_settings(settings), max_retries=0, cli_max_retries=0)` to preserve the original zero-retries test behavior, now independent of settings values.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Create config_objects.py with five frozen dataclasses | 3285926 |
| 2 | Update LLMCallService and all call sites to use LLMConfig | 3b968fd |

## Verification

- `python -c "from app.config_objects import LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig"` — exits 0
- `LLMConfig` is correctly frozen (FrozenInstanceError raised on attribute assignment)
- `python -c "from app.models.settings import Settings; from app.config_objects import LLMConfig"` — no circular import
- `grep -n "def call" app/services/llm_call.py` — shows `config: LLMConfig` parameter
- `grep -n "base_url=settings\." app/services/sentinel.py` — zero matches
- `grep -n "base_url=settings\." app/services/briefing.py` — zero matches
- All 31 tests pass

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. All config objects are constructed from live Settings ORM rows.

## Self-Check

Files created:
- app/config_objects.py — FOUND
- .planning/phases/01-foundation/01-03-SUMMARY.md — FOUND

Commits:
- 3285926 — FOUND (feat(01-03): create config_objects.py with five frozen dataclasses)
- 3b968fd — FOUND (feat(01-03): update LLMCallService and all call sites to use LLMConfig)

Test result: 31/31 passed

## Self-Check: PASSED
