# Phase 1: Foundation - Research

**Researched:** 2026-04-04
**Domain:** Python dataclasses, Flask DI container migration, service extraction refactoring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**LLM Service Design**
- D-01: Create `app/services/llm_call.py` containing `LLMCallService` — a stateless service that accepts `llm_client` as a constructor argument and provides a single `call()` method encapsulating the transport-switching logic (API vs CLI), timeout/retry resolution, and the `complete()`/`chat_completion()` fallback dispatch.
- D-02: `SentinelService`, `BriefingService`, and `api/settings.py:test_llm_connection` all delegate to `LLMCallService.call()` — their private `_call_llm`, `_settings`, `_prompt` helper methods are deleted.
- D-03: The `temperature` parameter (briefing uses 0.2, sentinel omits it) becomes an optional kwarg on `LLMCallService.call()` with a default of `None` (passthrough to LLMClient behavior).

**ServiceContainer Shape**
- D-04: Create `app/container.py` containing a mutable `@dataclass` named `ServiceContainer` with typed attributes: `llm_client`, `llm_call`, `verdict_parser`, `telegram_notifier`, `sentinel`, `briefing`, `coordinator`.
- D-05: `app.extensions["services"]` remains as the storage key, but now holds a `ServiceContainer` instance instead of a plain dict. Route handlers access via typed attributes: `container.sentinel` instead of `services["sentinel"]`.
- D-06: `ServiceContainer` implements `__getitem__` to delegate string-key lookups to `getattr` — this provides backwards compatibility for the 26 existing `extensions["services"]["key"]` references across routes and tests during the transition.
- D-07: All route handlers and tests are updated to use typed attribute access in this phase. The `__getitem__` shim remains as a safety net but all direct usages are migrated.

**Config Decomposition Strategy**
- D-08: Create `app/config_objects.py` containing five frozen `@dataclass` classes: `LLMConfig`, `AlertConfig`, `CallReductionConfig`, `TelegramConfig`, `CLIConfig`. Each is constructed from a `Settings` ORM row via a `from_settings(settings)` classmethod.
- D-09: The `Settings` ORM model and DB schema are NOT modified — all 25+ columns stay in one table. The decomposition is at the Python code boundary only.
- D-10: Services accept domain-specific config objects as method parameters (e.g., `LLMCallService.call(config: LLMConfig, ...)`) instead of the raw `Settings` singleton. Config objects are constructed at the call site where `Settings.singleton()` is currently called.

### Claude's Discretion
- Exact field grouping within each config dataclass (which fields go in LLMConfig vs CLIConfig, etc.)
- Whether to add a `NightlyConfig` dataclass or leave nightly_hour/nightly_minute on the coordinator directly
- Internal method signatures on `LLMCallService` (parameter naming, return type)
- Order of migration within the phase (LLMCallService first vs container first)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SRVC-01 | LLM invocation logic consolidated into a single LLMCallService class, eliminating duplication across sentinel.py, briefing.py, and api/settings.py | Duplication confirmed at sentinel.py:92-122, briefing.py:25-56, api/settings.py:63-102. All three share the same transport-dispatch shape. |
| SRVC-02 | SentinelService and BriefingService use the shared LLMCallService instead of private _call_llm methods | Both classes have a `_call_llm` method whose body is ~40 LOC of identical logic (difference: briefing passes `temperature=0.2`). Direct deletion path is clear. |
| DI-01 | Typed ServiceContainer dataclass replaces app.extensions["services"] string-keyed dict | Dict constructed at `__init__.py:317`. 7-key dict with string keys. Python `@dataclass` with `__getitem__` shim is the migration path. |
| DI-02 | All route handlers and services access dependencies via typed ServiceContainer attributes | 13 `extensions["services"]["key"]` references in `app/api/` and `app/__init__.py` web route closures. All must be migrated to attribute access. |
| DI-03 | Test fixtures inject dependencies via the typed ServiceContainer (shim maintained during transition) | 10 `extensions["services"][...]` references across 4 test files. `__getitem__` shim keeps them green during transition; attribute-access migration completes them. |
| CFG-01 | Settings god object decomposed into domain-specific config classes (LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig) | Settings ORM has 25+ fields confirmed in `app/models/settings.py`. Five frozen dataclasses cover all fields. |
| CFG-02 | Config classes are frozen dataclasses constructed from the single Settings ORM row (DB schema unchanged) | `Settings` table schema stays intact per D-09. Factory classmethods (`from_settings`) are the construction path. |
| CFG-03 | Services accept domain-specific config objects instead of the raw Settings singleton | `_settings()` helper methods on `SentinelService` and `BriefingService` are the injection points to replace. |
</phase_requirements>

---

## Summary

Phase 1 is a purely mechanical extraction refactor with zero schema changes. All three deliverables — `LLMCallService`, `ServiceContainer`, and config dataclasses — are Python-stdlib patterns (dataclasses, typing.Protocol compatibility shim) with no new library dependencies required.

The LLM duplication is the clearest case: `sentinel.py:92-122` and `briefing.py:25-56` are nearly identical 40-LOC blocks. The only behavioral difference is `temperature=0.2` in briefing vs. no temperature arg in sentinel. `api/settings.py:63-102` is a third variant with hardcoded `retries=0`, `max_tokens=8`, `temperature=0.0`. `LLMCallService.call()` must expose temperature, max_tokens, and retries as optional override kwargs so all three callers can specify exactly what they need.

The `ServiceContainer` migration has one critical constraint: four test files and seven API route files currently access services via `app.extensions["services"]["key"]`. The `__getitem__` shim (D-06) keeps all 23 existing string-key call sites green during the phase. D-07 mandates that all of them are migrated to typed attribute access before the phase closes — the shim stays as a safety net, not as a permanent accommodation. Tests in `test_sentinel_pipeline.py` and `test_briefing.py` also directly assign to `service.llm_client` and `service.telegram_notifier` after fetching the service; those attribute assignments continue to work unchanged since they target the service instance, not the container.

Config decomposition is the lowest-risk step: it introduces new read-only frozen dataclasses without modifying the Settings ORM, the DB schema, or any existing caller that currently works. The only change callers see is that they receive a typed `LLMConfig` instead of a raw `Settings` row.

**Primary recommendation:** Implement in order — LLMCallService first (proves extraction, simplest blast radius), ServiceContainer second (unblocks typed access everywhere), config dataclasses third (completes the phase with zero schema impact).

---

## Standard Stack

### Core (no new production dependencies required)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dataclasses` (stdlib) | Python 3.12 | `ServiceContainer` and frozen config dataclasses | No external dep; `frozen=True` gives immutability for config; mutable default for container |
| `typing` (stdlib) | Python 3.12 | Type annotations on `ServiceContainer` attributes and `LLMCallService.call()` signature | Already used throughout codebase |
| `app.services.llm_client.LLMResult` | existing | Return type for `LLMCallService.call()` | Already defined; no new type needed |
| Flask 3.0.3 | existing | `app.extensions` storage, `current_app` proxy | No change to Flask usage |
| SQLAlchemy 2.0.36 / Flask-SQLAlchemy 3.1.1 | existing | `Settings.singleton()` ORM call | No change; config dataclasses read from this |

### No New Dependencies

All patterns in this phase are implemented with Python stdlib. No `pip install` step is required for Phase 1.

---

## Architecture Patterns

### Recommended File Layout (Phase 1 additions)

```
app/
  services/
    llm_call.py      # NEW: LLMCallService
    sentinel.py      # MODIFIED: delete _call_llm, accept llm_call_service in __init__
    briefing.py      # MODIFIED: delete _call_llm/_settings/_prompt, accept llm_call_service
  api/
    settings.py      # MODIFIED: delete inline LLM call, use llm_call from container
  container.py       # NEW: ServiceContainer dataclass
  config_objects.py  # NEW: LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig
  __init__.py        # MODIFIED: build ServiceContainer instead of dict
```

### Pattern 1: LLMCallService — stateless extraction

`LLMCallService` is constructed once with the `LLMClient` instance and reused by all three callers. Its `call()` method accepts all parameters that vary between callers as explicit kwargs.

```python
# app/services/llm_call.py
from __future__ import annotations

from typing import Any

from app.services.llm_client import LLMClient, LLMResult


class LLMCallService:
    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client

    def call(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        base_url: str,
        api_key: str,
        model: str,
        transport: str,
        cli_backend: str,
        timeout_seconds: int,
        max_retries: int,
        cli_timeout_seconds: int,
        cli_max_retries: int,
        temperature: float | None = None,
    ) -> LLMResult:
        resolved_timeout = cli_timeout_seconds if transport == "cli" else timeout_seconds
        resolved_retries = cli_max_retries if transport == "cli" else max_retries

        call_kwargs: dict[str, Any] = dict(
            transport=transport,
            cli_backend=cli_backend,
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout_seconds=resolved_timeout,
            max_retries=resolved_retries,
            max_tokens=max_tokens,
        )
        if temperature is not None:
            call_kwargs["temperature"] = temperature

        if hasattr(self._client, "complete"):
            return self._client.complete(**call_kwargs)

        # Compatibility path for test doubles that only implement chat_completion.
        call_kwargs.pop("transport", None)
        call_kwargs.pop("cli_backend", None)
        return self._client.chat_completion(**call_kwargs)
```

**Critical note on the temperature=None default:** `LLMClient.complete()` has `temperature: float = 0.1` as its own default. When `LLMCallService.call()` omits temperature from `call_kwargs`, `LLMClient` uses its own default of 0.1. This preserves existing sentinel behavior (no explicit temperature → LLMClient default). Briefing explicitly passes `temperature=0.2`. The test-LLM endpoint explicitly passes `temperature=0.0`. All three callers get the right behavior through the optional kwarg.

**Critical note on test doubles:** `DummyLLM` in `test_sentinel_pipeline.py` and `test_briefing.py` only implements `chat_completion()`, not `complete()`. The `hasattr(self._client, "complete")` guard in the existing code handles this — `LLMCallService` must preserve this guard exactly. After `LLMCallService` is wired in, tests that currently assign `sentinel.llm_client = DummyLLM()` will need updating: the relevant `DummyLLM` now needs to be injected into `LLMCallService._client`, which means injecting a new `LLMCallService(DummyLLM())` into the sentinel service or directly replacing `sentinel.llm_call_service._client`.

The cleanest approach: `SentinelService.__init__` accepts `llm_call_service: LLMCallService` as a parameter, and tests inject `LLMCallService(DummyLLM())` at construction time or replace `sentinel.llm_call_service._client = DummyLLM()` after retrieval from the container.

### Pattern 2: ServiceContainer with __getitem__ shim

```python
# app/container.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ServiceContainer:
    llm_client: Any
    llm_call: Any
    verdict_parser: Any
    telegram_notifier: Any
    sentinel: Any
    briefing: Any
    coordinator: Any

    def __getitem__(self, key: str) -> Any:
        """Backwards-compatibility shim for string-key access during migration."""
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        """Backwards-compatibility shim for test injection during migration."""
        setattr(self, key, value)
```

**Why `__setitem__` is also required:** `test_api.py:85` does `app.extensions["services"]["llm_client"] = _LLMOk()`. Without `__setitem__`, this raises `TypeError: 'ServiceContainer' object does not support item assignment`. The shim for writes is as important as the shim for reads.

**Container attribute names must match existing string keys exactly:** The dict keys in `__init__.py:317` are `"llm_client"`, `"cli_runner"`, `"verdict_parser"`, `"telegram"`, `"sentinel"`, `"briefing"`, `"coordinator"`. The CONTEXT.md (D-04) specifies `telegram_notifier` rather than `telegram` for the container attribute. This is a rename — any test or route that currently uses `services["telegram"]` must be updated to `container.telegram_notifier` (or the `__getitem__` shim must map `"telegram"` to `"telegram_notifier"`). The simplest approach: keep the attribute name as `telegram_notifier` in the typed container and migrate the one `api/telegram.py` call site to use the new name.

### Pattern 3: Frozen config dataclasses with from_settings classmethod

```python
# app/config_objects.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.settings import Settings


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    provider: str
    transport: str
    timeout_seconds: int
    max_retries: int
    cli_backend: str
    cli_timeout_seconds: int
    cli_max_retries: int

    @classmethod
    def from_settings(cls, s: "Settings") -> "LLMConfig":
        return cls(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            provider=s.llm_provider,
            transport=(s.llm_transport or "api").strip().lower(),
            timeout_seconds=s.llm_timeout_seconds,
            max_retries=s.llm_max_retries,
            cli_backend=s.cli_backend,
            cli_timeout_seconds=s.cli_timeout_seconds,
            cli_max_retries=s.cli_max_retries,
        )


@dataclass(frozen=True)
class AlertConfig:
    cooldown_minutes: int
    rate_limit_count: int
    rate_limit_window_seconds: int
    telegram_token: str | None
    telegram_chat_id: str | None

    @classmethod
    def from_settings(cls, s: "Settings") -> "AlertConfig":
        return cls(
            cooldown_minutes=s.alert_cooldown_minutes,
            rate_limit_count=s.alert_rate_limit_count,
            rate_limit_window_seconds=s.alert_rate_limit_window_seconds,
            telegram_token=s.telegram_token,
            telegram_chat_id=s.telegram_chat_id,
        )


@dataclass(frozen=True)
class CallReductionConfig:
    dedup_window_seconds: int
    container_rate_limit_count: int
    container_rate_limit_window_seconds: int
    keyword_flush_delay_lines: int

    @classmethod
    def from_settings(cls, s: "Settings") -> "CallReductionConfig":
        return cls(
            dedup_window_seconds=s.dedup_window_seconds,
            container_rate_limit_count=s.container_rate_limit_count,
            container_rate_limit_window_seconds=s.container_rate_limit_window_seconds,
            keyword_flush_delay_lines=s.keyword_flush_delay_lines,
        )


@dataclass(frozen=True)
class TelegramConfig:
    token: str | None
    chat_id: str | None

    @classmethod
    def from_settings(cls, s: "Settings") -> "TelegramConfig":
        return cls(token=s.telegram_token, chat_id=s.telegram_chat_id)


@dataclass(frozen=True)
class CLIConfig:
    backend: str
    timeout_seconds: int
    max_retries: int

    @classmethod
    def from_settings(cls, s: "Settings") -> "CLIConfig":
        return cls(
            backend=s.cli_backend,
            timeout_seconds=s.cli_timeout_seconds,
            max_retries=s.cli_max_retries,
        )
```

**Field grouping rationale (Claude's discretion):** `LLMConfig` contains all fields needed by `LLMCallService.call()`. `AlertConfig` contains all fields consumed by `_send_alert_if_allowed` (Phase 4 scope, but already correct here). `TelegramConfig` is a subset of `AlertConfig` — it exists separately because `TelegramNotifier.send_message()` only needs token + chat_id, not cooldown or rate-limit fields. `CLIConfig` groups CLI-specific overrides that are also present in `LLMConfig`; it is useful for the coordinator and for any future CLI-only configuration surface. `CallReductionConfig` groups the dedup/rate-limit call-volume fields. Nightly scheduling fields (`nightly_hour`, `nightly_minute`) stay in `Settings.singleton()` accessed directly by the coordinator — no `NightlyConfig` dataclass is needed in this phase.

### Pattern 4: Wiring in create_app()

```python
# In app/__init__.py create_app(), replacing the dict construction

from app.container import ServiceContainer
from app.services.llm_call import LLMCallService

# ... existing service construction ...
llm_call_service = LLMCallService(llm_client=llm_client)
sentinel_service = SentinelService(
    llm_call_service=llm_call_service,
    verdict_parser=verdict_parser,
    telegram_notifier=telegram_notifier,
)
briefing_service = BriefingService(llm_call_service=llm_call_service)

app.extensions["services"] = ServiceContainer(
    llm_client=llm_client,
    llm_call=llm_call_service,
    verdict_parser=verdict_parser,
    telegram_notifier=telegram_notifier,
    sentinel=sentinel_service,
    briefing=briefing_service,
    coordinator=coordinator,
)
```

**Note:** `cli_runner` is currently in the dict as `"cli_runner"` but is not referenced by any route handler or test. The CONTEXT.md (D-04) does not include it in the ServiceContainer. It can be dropped from the container (remains a local variable in `create_app`) or included for completeness. Dropping it simplifies the container without breaking anything.

### Anti-Patterns to Avoid

- **Injecting Settings singleton into LLMCallService constructor:** `LLMCallService` should receive the resolved config values (or a `LLMConfig` object) at call time, not at construction time. Constructing with settings creates a stale-config risk since settings can be updated via the API at runtime.
- **Putting `from_settings()` logic inside the Settings ORM model:** The ORM model must not import config dataclasses (circular import risk). The `from_settings(settings)` classmethod belongs on the config dataclass, not on the ORM model.
- **Removing the `__getitem__` shim before all call sites are migrated:** The 10 test-file references and 13 route-file references must all be migrated within this phase before the shim can be considered redundant. Do not remove it until `grep -r 'extensions\["services"\]\["'` returns zero results.
- **Mutating a frozen config dataclass:** `CallReductionConfig` is `frozen=True`. Any code that previously did `settings.dedup_window_seconds = X` must call `Settings.singleton()` directly and use the ORM setattr pattern — frozen dataclasses are read models only.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Typed DI container | Custom metaclass, descriptor-based proxy, or importable singleton | Plain `@dataclass` with typed fields | A 10-field dataclass is readable, debuggable, and requires zero learning curve |
| Config immutability | Custom `__setattr__` guard | `@dataclass(frozen=True)` | stdlib, raises `FrozenInstanceError` on write attempts, works with type checkers |
| Backwards-compatible container access | A full proxy class or `__getattr__` magic | `__getitem__` + `__setitem__` delegating to `getattr`/`setattr` | Two methods, zero risk, easy to grep and delete later |
| Transport resolution logic | Duplicating in each service | `LLMCallService.call()` with the resolved transport/timeout/retry logic | The entire reason for this phase |

**Key insight:** Every custom solution here is more complex than the stdlib alternative. The value of this phase is elimination of duplication, not introduction of clever abstractions.

---

## Common Pitfalls

### Pitfall 1: Test doubles break after LLMCallService injection
**What goes wrong:** Tests in `test_sentinel_pipeline.py` and `test_briefing.py` replace `sentinel.llm_client` and `briefing.llm_client` directly after fetching the service from the container. After the refactor, `SentinelService` no longer has a `llm_client` attribute — it has `llm_call_service`. The test assignment silently no longer replaces the real client.
**Why it happens:** Tests assign to the attribute they found before the refactor. After the refactor, the relevant attribute is one level deeper (`service.llm_call_service._client`).
**How to avoid:** When migrating service constructors, also update every test that currently assigns `service.llm_client = DummyLLM()` to assign `service.llm_call_service._client = DummyLLM()`. Do this in the same commit as the service change.
**Warning signs:** Tests pass when `DummyLLM` is injected but actually call a real LLM endpoint (network timeout in CI), or tests fail with `AttributeError: 'SentinelService' has no attribute 'llm_client'`.

### Pitfall 2: "telegram" key renamed to "telegram_notifier" breaks existing call sites
**What goes wrong:** The current dict key is `"telegram"`. D-04 specifies the container attribute as `telegram_notifier`. If `__getitem__` delegates naively via `getattr(self, key)`, then `container["telegram"]` raises `AttributeError` because the attribute is named `telegram_notifier`.
**Why it happens:** The attribute name in the container (D-04) differs from the existing string key.
**How to avoid:** Either (a) keep the attribute name as `telegram` in the container to match the existing key, or (b) add a `_KEY_MAP = {"telegram": "telegram_notifier"}` lookup in `__getitem__` to bridge the rename. Option (a) is simpler for this phase since only `api/telegram.py:13` uses this key and can be migrated to `container.telegram_notifier` immediately.
**Warning signs:** `AttributeError: 'ServiceContainer' object has no attribute 'telegram'` during test runs.

### Pitfall 3: Circular import when config_objects.py imports Settings
**What goes wrong:** `app/config_objects.py` contains `from_settings(cls, s: Settings)`. If `Settings` is imported at module level, `app/config_objects.py` imports `app/models/settings.py` which imports `app/extensions.py` which imports `flask_sqlalchemy`. This is fine. The risk is the reverse: `app/models/settings.py` must NOT import `app/config_objects.py`, or a circular dependency is created.
**Why it happens:** Bidirectional imports between models and config layer.
**How to avoid:** Use `TYPE_CHECKING` guard for the Settings type annotation in config_objects.py (as shown in the code example above). At runtime, the `from_settings` method receives a Settings instance; the type annotation is only needed by type checkers.
**Warning signs:** `ImportError: cannot import name 'Settings' from partially initialized module` at test collection time.

### Pitfall 4: Frozen config constructed once per request vs. once per call
**What goes wrong:** Config dataclasses are constructed from `Settings.singleton()` at the call site. If this construction happens inside a tight loop (e.g., `process_chunk` called on every log line), it adds one DB round-trip per call.
**Why it happens:** D-10 specifies that config objects are constructed at the call site where `Settings.singleton()` is currently called. In `process_chunk`, `Settings.singleton()` is already called per chunk. The behavior is unchanged in terms of DB access frequency.
**How to avoid:** No change required for Phase 1. This is an optimization consideration for Phase 2+ when the repository layer is introduced. Document as a known pattern.
**Warning signs:** Not an issue at Phase 1 scale — just worth knowing the config is ephemeral by design.

### Pitfall 5: settings["telegram"] write path silently fails with frozen TelegramConfig
**What goes wrong:** `AlertConfig` and `TelegramConfig` are `frozen=True`. The settings API PUT handler and settings page form POST both mutate `Settings.singleton()` fields directly (`settings.telegram_token = value`). This must continue to target the ORM row, not a frozen config dataclass.
**Why it happens:** Confusion between the write path (ORM row mutation) and the read path (frozen config from ORM row).
**How to avoid:** The write path must never touch a config dataclass. Config dataclasses are constructed fresh from `Settings.singleton()` on each read. The ORM Settings model remains the single writable source of truth.
**Warning signs:** Settings page POST appears to succeed (200 response) but values do not persist — would indicate config object being mutated (silently discarded) instead of ORM row.

---

## Code Examples

Verified patterns from direct codebase inspection:

### Existing _call_llm signature (sentinel.py:92-122)
```python
def _call_llm(self, *, settings: Settings, messages: list[dict[str, str]], max_tokens: int):
    transport = (settings.llm_transport or "api").strip().lower()
    timeout_seconds = settings.llm_timeout_seconds
    retries = settings.llm_max_retries
    if transport == "cli":
        timeout_seconds = settings.cli_timeout_seconds
        retries = settings.cli_max_retries

    if hasattr(self.llm_client, "complete"):
        return self.llm_client.complete(
            transport=transport,
            cli_backend=settings.cli_backend,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            messages=messages,
            timeout_seconds=timeout_seconds,
            max_retries=retries,
            max_tokens=max_tokens,
        )
    # Compatibility path for test doubles
    return self.llm_client.chat_completion(...)
```

### Briefing difference (briefing.py:25-56)
```python
# Identical to above except:
temperature=0.2,  # added to both complete() and chat_completion() calls
```

### test_llm_connection variant (api/settings.py:63-102)
```python
# Differences from the standard _call_llm:
retries = 0  # hardcoded, not from settings
max_tokens=8  # hardcoded
temperature=0.0  # hardcoded
# No cli_max_retries override — retries=0 applies to both transports
```

### Existing test injection pattern (test_sentinel_pipeline.py:40-41)
```python
sentinel = app.extensions["services"]["sentinel"]
sentinel.llm_client = DummyLLM()  # Direct attribute assignment on service
```

### Existing dict construction (app/__init__.py:317-325)
```python
app.extensions["services"] = {
    "llm_client": llm_client,
    "cli_runner": cli_runner,
    "verdict_parser": verdict_parser,
    "telegram": telegram_notifier,
    "sentinel": sentinel_service,
    "briefing": briefing_service,
    "coordinator": coordinator,
}
```

### Settings ORM fields by domain group
```
LLMConfig fields: llm_base_url, llm_api_key, llm_model, llm_provider, llm_transport,
                  llm_timeout_seconds, llm_max_retries, cli_backend, cli_timeout_seconds,
                  cli_max_retries
AlertConfig fields: alert_cooldown_minutes, alert_rate_limit_count,
                    alert_rate_limit_window_seconds, telegram_token, telegram_chat_id
CallReductionConfig fields: dedup_window_seconds, container_rate_limit_count,
                             container_rate_limit_window_seconds, keyword_flush_delay_lines
TelegramConfig fields: telegram_token, telegram_chat_id
CLIConfig fields: cli_backend, cli_timeout_seconds, cli_max_retries
Remaining on Settings (coordinator-owned): nightly_hour, nightly_minute
Buffer fields (not in a Phase 1 dataclass): max_input_chars, max_input_tokens,
                                             reserved_output_tokens,
                                             token_estimation_strategy, keyword_list,
                                             updated_at
```

---

## Environment Availability

This phase is purely Python code/refactoring — no external tool dependencies, no CLI utilities, no databases beyond what the existing test suite already uses.

Step 2.6: SKIPPED (no external dependencies introduced in Phase 1)

---

## Migration Site Inventory

### All `app.extensions["services"]` references that must be updated

**In `app/__init__.py` (web route closures — 6 references):**
- Line 140: `coordinator = app.extensions["services"]["coordinator"]`
- Line 178: `app.extensions["services"]["coordinator"].refresh_schedule()`
- Line 189: `app.extensions["services"]["coordinator"].trigger_reconcile()`
- Line 201: `app.extensions["services"]["coordinator"].trigger_reconcile()`
- Line 240: `app.extensions["services"]["briefing"].generate_report()`
- Lines 271, 278: `sentinel = app.extensions["services"]["sentinel"]`

**In `app/api/` (7 references across 5 files):**
- `api/settings.py:57`: `services["coordinator"]`
- `api/settings.py:66`: `services["llm_client"]`
- `api/exclusions.py:32`: `services["coordinator"]`
- `api/exclusions.py:44`: `services["coordinator"]`
- `api/telegram.py:13`: `services["telegram"]`
- `api/reports.py:27`: `services["briefing"]`
- `api/sentinel.py:13,24,36`: `services["coordinator"]`, `services["sentinel"]` (3 references)

**In `tests/` (10 references across 3 files):**
- `test_sentinel_pipeline.py`: 6 `services["sentinel"]` reads + 2 direct attribute assignments
- `test_briefing.py`: 2 `services["briefing"]` reads + 2 direct attribute assignments
- `test_api.py`: 2 `services["llm_client"] = ...` write assignments

**Total: 23 references to migrate** (the `__getitem__`/`__setitem__` shim keeps all 23 green until migration is complete)

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| String-keyed dict for DI | Typed `@dataclass` container | `@dataclass` is the modern Python pattern; Flask-Injector and similar are overkill at this scale |
| Global god-object config | Frozen domain config dataclasses | Standard "value object" pattern from DDD; Python `@dataclass(frozen=True)` is the idiomatic form |
| Triplicated service logic | Extracted service class | Standard service layer extraction per Cosmic Python |

---

## Open Questions

1. **`cli_runner` in ServiceContainer?**
   - What we know: `cli_runner` is in the current dict (`"cli_runner": cli_runner`) but no route handler or test file references it by key. It is passed to `LLMClient.__init__()` at construction but not used as a separately-injected service.
   - What's unclear: Whether future phases will need to inject a different `CLIBackendRunner`.
   - Recommendation: Omit from the Phase 1 `ServiceContainer` (it's a local variable in `create_app`). The container should only include services that are accessed by external consumers (routes, tests, coordinator). Add it in a later phase if needed.

2. **Buffer config dataclass in Phase 1?**
   - What we know: The Settings model has 5 buffer-related fields (`max_input_chars`, `max_input_tokens`, `reserved_output_tokens`, `token_estimation_strategy`, `keyword_list`). These are used in `log_buffer.py` and `sentinel.py`. D-08 lists five config classes that do NOT include a `BufferConfig`.
   - What's unclear: Whether to include buffer fields in a `BufferConfig` dataclass now or defer to Phase 2.
   - Recommendation: Defer. The five dataclasses in D-08 cover the fields needed by the services being refactored in Phase 1. Buffer fields are internal to `LogBuffer` logic, which is not being refactored in this phase.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection (no external sources required for this phase):
  - `app/services/sentinel.py:92-122` — confirmed `_call_llm` exact signature
  - `app/services/briefing.py:25-56` — confirmed `_call_llm` with `temperature=0.2`
  - `app/api/settings.py:63-102` — confirmed test-LLM inline call with `retries=0, max_tokens=8, temperature=0.0`
  - `app/__init__.py:317-325` — confirmed dict construction with exact key names
  - `app/models/settings.py` — confirmed all 25 field names and types
  - `app/services/llm_client.py` — confirmed `LLMResult` dataclass, `complete()` and `chat_completion()` signatures
  - `tests/test_sentinel_pipeline.py`, `tests/test_briefing.py`, `tests/test_api.py` — confirmed all injection patterns
- Python stdlib dataclasses documentation — https://docs.python.org/3/library/dataclasses.html — frozen=True behavior, __getitem__ not auto-generated
- Architecture Patterns with Python (Cosmic Python) — https://www.cosmicpython.com/book/chapter_13_dependency_injection.html — typed DI container patterns

### Secondary (MEDIUM confidence)
- Prior project research in `.planning/research/ARCHITECTURE.md` — HIGH confidence (direct codebase analysis)
- Prior project research in `.planning/research/PITFALLS.md` — HIGH confidence (verified against official Flask/SQLAlchemy docs)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns are stdlib or existing project dependencies; no new libraries
- Architecture: HIGH — based on direct code inspection of every file that will be modified
- Migration inventory: HIGH — grepped all 23 call sites; exact line numbers verified
- Pitfalls: HIGH — all five pitfalls derived from direct code inspection of the test injection patterns and the temperature/retries variance

**Research date:** 2026-04-04
**Valid until:** This is a code-level analysis tied to the current codebase state. Valid until any of the canonical reference files (sentinel.py, briefing.py, api/settings.py, __init__.py, test files) are modified.
