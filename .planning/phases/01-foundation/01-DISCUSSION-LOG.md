# Phase 1: Foundation - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 01-foundation
**Areas discussed:** LLM Service Design, ServiceContainer Shape, Config Decomposition Strategy, Test Shim Approach
**Mode:** Auto (all areas auto-selected, recommended defaults chosen)

---

## LLM Service Design

| Option | Description | Selected |
|--------|-------------|----------|
| Stateless service wrapping LLMClient | New class accepts llm_client, provides call() with transport-switching | ✓ |
| Extend LLMClient directly | Add transport-switching to existing LLMClient class | |
| Mixin class | Shared _call_llm as a mixin inherited by services | |

**User's choice:** [auto] Stateless service wrapping LLMClient (recommended default)
**Notes:** Preserves LLMClient's existing retry/transport logic untouched. New class adds the Settings→transport resolution layer.

---

## ServiceContainer Shape

| Option | Description | Selected |
|--------|-------------|----------|
| Mutable dataclass | @dataclass with typed attributes, __getitem__ shim for backwards compat | ✓ |
| NamedTuple | Immutable container, forces reconstruction on any change | |
| TypedDict | Dict-like but typed, no attribute access syntax | |

**User's choice:** [auto] Mutable dataclass (recommended default)
**Notes:** Tests need to swap services (e.g., `container.llm_client = DummyLLM()`). Mutable dataclass supports this.

---

## Config Decomposition Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Frozen dataclasses | @dataclass(frozen=True) with from_settings() classmethod | ✓ |
| Pydantic models | Pydantic v2 BaseModel with model_validate | |
| Plain dicts | Named dicts per domain, no type safety | |

**User's choice:** [auto] Frozen dataclasses (recommended default)
**Notes:** Lighter weight than Pydantic for read-only config. Pydantic already used for VerdictParser — consistency argument applies but frozen dataclasses are sufficient for config objects.

---

## Test Shim Approach

| Option | Description | Selected |
|--------|-------------|----------|
| Dict shim + full migration | __getitem__ on container for compat, but migrate all 26 references in this phase | ✓ |
| Dict shim only | Keep __getitem__, don't update existing references | |
| Breaking migration | Remove dict access, update all 26 references with no shim | |

**User's choice:** [auto] Dict shim + full migration (recommended default)
**Notes:** All route handlers and tests updated to typed access. Shim remains as safety net but is not relied upon.

---

## Claude's Discretion

- Exact field grouping within each config dataclass
- Whether to add NightlyConfig dataclass
- Internal method signatures on LLMCallService
- Order of migration within the phase

## Deferred Ideas

None — discussion stayed within phase scope
