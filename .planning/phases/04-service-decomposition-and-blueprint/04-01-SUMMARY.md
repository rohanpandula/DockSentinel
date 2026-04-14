---
phase: 04-service-decomposition-and-blueprint
plan: 01
subsystem: services
tags: [refactor, services, alerts, strategy-pattern, protocol, dependency-injection]

# Dependency graph
requires:
  - phase: 02-repository-layer
    provides: AnalysisEventRepository.find_alert_duplicate / count_recent_alerts (consumed by AlertService)
  - phase: 03-config-and-extensions
    provides: AlertConfig dataclass + from_settings classmethod (consumed by AlertService.maybe_send)
provides:
  - app/services/alerts.py with AlertStrategy Protocol, TelegramAlertStrategy, AlertService.maybe_send
  - ServiceContainer.alert_strategy and ServiceContainer.alert_service typed attrs
  - SentinelService freed from any Telegram references and from inline alert-gating logic
  - Test injection seam at sentinel.alert_service.strategy (Protocol-shaped)
affects: [04-02-composition-extraction, 04-03-blueprint-extraction, 04-04-app-init-shrink, 05-observability, future-slack-discord-email-transports]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Strategy Pattern via typing.Protocol (structural typing, no abc.ABC, no @runtime_checkable)"
    - "Service-owned config injection (Sentinel passes AlertConfig.from_settings(settings) into AlertService.maybe_send)"
    - "Pure (commit-free) service modules — caller owns transaction boundary (Phase 2 D-01 inheritance)"

key-files:
  created:
    - app/services/alerts.py
  modified:
    - app/container.py
    - app/services/sentinel.py
    - app/__init__.py
    - tests/test_sentinel_pipeline.py

key-decisions:
  - "AlertStrategy is typing.Protocol (not abc.ABC) — structural typing matches the existing service layer style and avoids forcing TelegramAlertStrategy to inherit"
  - "SentinelService keeps the `if verdict.classification == 'critical':` gate (CONTEXT §specifics) — AlertService is transport-agnostic, not classification-aware"
  - "telegram_notifier remains on ServiceContainer (D-05) — still consumed by app/api/telegram.py test endpoint; removing it would break the API surface"
  - "Test seam moved from sentinel.telegram_notifier to sentinel.alert_service.strategy via _FakeAlertStrategy (CONTEXT D-14 discretion, P-02 Option C)"
  - "DummyTelegram test class retained as zero-risk dead code (no other reference) — explicit removal is out of scope"

patterns-established:
  - "Protocol-shaped strategy: `def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]:` is the canonical alert-transport interface for future Slack/Discord/email backends"
  - "AlertService.maybe_send is gate -> format -> dispatch and is explicitly commit-free (docstring contract)"
  - "Container fields for alert_strategy / alert_service use unquoted forward refs under `from __future__ import annotations` with TYPE_CHECKING import — mirrors existing repository-attr pattern"

requirements-completed: [SRVC-03, SRVC-04]

# Metrics
duration: 18min
completed: 2026-04-14
---

# Phase 04 Plan 01: AlertService extraction with Protocol-based strategy

**AlertService extracted into app/services/alerts.py with AlertStrategy Protocol + TelegramAlertStrategy; SentinelService no longer holds telegram references; container exposes typed alert_strategy / alert_service attrs; 31/31 tests green via 5-line test-seam swap.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-04-14 (worktree session)
- **Completed:** 2026-04-14
- **Tasks:** 3
- **Files modified:** 5 (1 created, 4 modified)
- **LOC delta:** +102 / -36 (net +66; new module is +76, sentinel.py shrank by ~21 lines)

## Accomplishments

- New `app/services/alerts.py` module encapsulates the cooldown + global-rate-limit + format + dispatch pipeline (76 LOC, zero `db.session` references)
- `SentinelService.__init__` no longer accepts `telegram_notifier`; `_send_alert_if_allowed` deleted entirely; critical-alert branch now calls `self.alert_service.maybe_send(event, AlertConfig.from_settings(settings))`
- `ServiceContainer` extended with two typed attrs (`alert_strategy: AlertStrategy`, `alert_service: AlertService`) inserted between `telegram_notifier` and `sentinel`; `_KEY_MAP` shim left untouched (no string-key callers)
- `create_app()` instantiates `TelegramAlertStrategy(telegram_notifier)` and `AlertService(strategy=alert_strategy, event_repo=event_repo)` and threads both through the SentinelService constructor and the ServiceContainer kwargs
- 5-line mechanical test-seam swap: `sentinel.telegram_notifier = DummyTelegram()` → `sentinel.alert_service.strategy = _FakeAlertStrategy()` (Protocol-compatible fake)
- Locked error strings preserved byte-identically — `"duplicate alert suppressed by cooldown"` and `"global rate limit exceeded"` (asserted at test_sentinel_pipeline.py:95 and :151)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create app/services/alerts.py** — `14b065b` (feat) — Protocol + TelegramAlertStrategy + AlertService.maybe_send
2. **Task 2: Extend ServiceContainer + rewire SentinelService + factory wiring** — `d953420` (refactor) — three surgical edits across container.py, sentinel.py, __init__.py
3. **Task 3: Swap test injection seam** — `9fb73a8` (test) — _FakeAlertStrategy + 5 line replacements

_Note: Tasks were marked `tdd="true"` but functioned as code-motion (no behavior change), so a single feat/refactor/test commit per task was the appropriate granularity. The contract was already test-covered before extraction (test_sentinel_pipeline.py asserts the exact error strings end-to-end), so the existing suite served as the RED guardrail._

## Files Created/Modified

- `app/services/alerts.py` *(created, 76 LOC)* — AlertStrategy Protocol, TelegramAlertStrategy, AlertService with `maybe_send(event, config) -> tuple[bool, str | None]` and `_format_message(event)` static helper
- `app/container.py` *(modified, +3 lines)* — TYPE_CHECKING import for AlertService/AlertStrategy + two typed attrs on ServiceContainer
- `app/services/sentinel.py` *(modified, +6 / -27)* — TYPE_CHECKING AlertService import; ctor swap (`telegram_notifier` → `alert_service`); critical branch now calls `alert_service.maybe_send`; deleted `_send_alert_if_allowed`; extended config-objects import to add `AlertConfig`
- `app/__init__.py` *(modified, +5 / -2)* — top-level import of `AlertService, TelegramAlertStrategy`; instantiation block before `SentinelService(...)`; constructor + ServiceContainer kwargs updated
- `tests/test_sentinel_pipeline.py` *(modified, +10 / -5)* — added `_FakeAlertStrategy` class; replaced 5 occurrences of the seam line with the new attribute path

## Decisions Made

- **AlertConfig sourced via classmethod, passed at call site (not stored on AlertService).** Each `maybe_send` call resolves a fresh `AlertConfig.from_settings(settings)` — preserves the existing behavior where settings can be live-edited via the dashboard between alerts. Storing it on the service would cache stale config.
- **`@runtime_checkable` deliberately omitted on AlertStrategy.** No `isinstance(x, AlertStrategy)` check exists anywhere in the codebase (verified via Grep), and the Protocol is consumed only via static typing + duck dispatch at the call site. Adding `@runtime_checkable` would imply a runtime contract we don't enforce.
- **TelegramAlertStrategy is a thin wrapper, not a subclass of TelegramNotifier.** Composition over inheritance — keeps TelegramNotifier reusable from `app/api/telegram.py` (which still consumes it directly through `container.telegram_notifier`), and lets future Slack/Discord transports follow the same shape without a parallel inheritance hierarchy.
- **`telegram_notifier` field stayed on ServiceContainer (D-05).** Removing it would have required also touching `app/api/telegram.py` — explicitly out of scope for plan 04-01 (which is wave-1, depends_on=[]). That coupling will be revisited in a later plan if/when the Telegram test endpoint is itself migrated to the strategy.

## Deviations from Plan

None — plan executed exactly as written. All three tasks landed in the order specified, all six grep-based verification checks passed on the first run, and the test suite went from 31/31 green (baseline) to 31/31 green (post-Task-3) with no intermediate fixes required.

## Issues Encountered

None. The plan's pre-supplied verbatim Code Examples and unambiguous edit instructions made this a pure code-motion exercise. The only friction was a series of `READ-BEFORE-EDIT` reminders triggered after each Edit call (cosmetic — files had been read at session start; edits succeeded regardless).

## Next Phase Readiness

**Plan 04-02 (composition extraction)** is unblocked and can proceed immediately:

- `ServiceContainer.alert_service` and `ServiceContainer.alert_strategy` are wired and ready to be instantiated from `app/composition.py` in the next plan
- The instantiation block to lift into `composition.py` is exactly the 11-line region in `app/__init__.py` between `cli_runner = ...` (line ~301) and the `app.extensions["services"] = ServiceContainer(...)` assignment (line ~327) — including the new `alert_strategy = TelegramAlertStrategy(telegram_notifier)` and `alert_service = AlertService(strategy=alert_strategy, event_repo=event_repo)` lines added in this plan
- No state-machine or transaction-scope concerns introduced — `AlertService.maybe_send` is commit-free; the existing `db.session.commit()` at `process_chunk` line ~261 still owns the transaction (D-01 invariant preserved)
- `app/api/telegram.py` continues to read `container.telegram_notifier` unchanged — no API contract regression

**Plan 04-04 (app/__init__.py shrink)** is informed: this plan added 5 lines to `app/__init__.py` (one import + two instantiations + two ServiceContainer kwargs). The shrink target excludes these because they will move to `composition.py` in 04-02.

## Self-Check: PASSED

Verified during execution:
- `app/services/alerts.py` exists (76 LOC, contains `class AlertStrategy(Protocol)`, `class TelegramAlertStrategy`, `class AlertService` with `maybe_send`)
- All three task commits exist in git log: `14b065b`, `d953420`, `9fb73a8` (verified via `git log --oneline -5`)
- `pytest -q` reports `31 passed` (baseline preserved)
- `grep -n 'db\.session' app/services/alerts.py` returns 0 matches (Phase 2 D-01 invariant)
- `grep -n '_send_alert_if_allowed' app/services/sentinel.py` returns 0 matches (method deleted)
- `grep -n 'self\.telegram_notifier' app/services/sentinel.py` returns 0 matches (attribute removed)
- `_FakeAlertStrategy` appears 6 times in `tests/test_sentinel_pipeline.py` (1 class def + 5 reassignments) — exactly as specified

---
*Phase: 04-service-decomposition-and-blueprint*
*Completed: 2026-04-14*
