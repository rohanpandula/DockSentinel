# DockSentinel Total Refactor

## What This Is

DockSentinel is a self-hosted AIOps observability agent for Docker environments. It monitors container logs in real-time, uses LLMs (API or CLI backends) for semantic triage, sends Telegram alerts, and generates nightly health briefings. The MVP is complete (v0.2) with a Flask/Jinja2 dashboard, SQLite persistence, and 31 tests across 10 test files (~3,309 LOC total).

This milestone is a full architectural refactor of the existing MVP codebase to eliminate tech debt, improve testability, and lay a clean foundation for the features in ROADMAP.md (React SPA, fix suggestions, notification center, RAG). No new features — this is purely structural.

## Core Value

Every refactoring change must keep the existing API contract intact (all endpoints continue to work) and all 31 tests passing — structure improves without breaking behavior.

## Requirements

### Validated

- ✓ Real-time container log monitoring via Docker SDK — existing
- ✓ Dual LLM transport (API + CLI backends) with retry logic — existing
- ✓ 4-layer call reduction (prefilter, chunk dedup, rate limiting, keyword batching) — existing
- ✓ Telegram alerts with cooldown and global rate limiting — existing
- ✓ Nightly briefing generation with LLM + fallback markdown — existing
- ✓ Flask/Jinja2 dashboard with settings, exclusions, insights, reports, prompts — existing
- ✓ Prompt Studio with versioned templates — existing
- ✓ SQLite persistence with singleton settings pattern — existing
- ✓ RuntimeCoordinator with file-lock singleton enforcement — existing
- ✓ Docker Compose deployment — existing
- ✓ Single LLMCallService for all LLM invocation — Phase 1
- ✓ Typed ServiceContainer for dependency injection — Phase 1
- ✓ Domain-specific frozen config dataclasses (LLMConfig, AlertConfig, CallReductionConfig, TelegramConfig, CLIConfig) — Phase 1

### Active

- [ ] Repository pattern for DB access (AnalysisEvent, Settings, Prompts, Reports)
- [ ] Move web routes out of app factory into blueprints; replace raw SQL migrations with Alembic
- [ ] API pagination and Pydantic request/response validation on all list endpoints
- [ ] Refactor SentinelService into composable pipeline stages (log buffering, LLM calls, dedup, rate limiting, alerts)
- [ ] Create AlertStrategy abstraction (prep for Slack/email/Discord)
- [ ] Improve test coverage to ~80%+ with integration tests, shared fixtures, and coverage measurement
- [ ] Fix Docker setup (non-root user, health check, build cache, data volume)

### Out of Scope

- React SPA frontend — deferred to ROADMAP Phase 1
- Fix suggestions / knowledge base — deferred to ROADMAP Phase 2
- SMTP email alerts / notification rules — deferred to ROADMAP Phase 3
- RAG / vector database — deferred to ROADMAP Phase 4
- Multi-channel alerts, anomaly detection, auth, multi-host — deferred to ROADMAP Phase 5
- PostgreSQL migration — not needed for refactor, SQLite is fine
- New API endpoints — only restructure existing ones
- Framework migration — Flask stays, no FastAPI or Django

## Context

**Codebase state (v0.2, ~3,309 LOC):**

- `app/__init__.py` (334 LOC) — Flask factory mixing app creation with 6 web route handlers and hardcoded schema migration SQL
- `app/services/sentinel.py` (361 LOC) — monolithic service mixing log buffering, LLM calls, dedup, rate limiting, and alerts
- `app/services/briefing.py` (147 LOC) — duplicates `_settings()`, `_prompt()`, `_call_llm()` from sentinel.py (~40 LOC duplication)
- `app/api/settings.py` (102 LOC) — also contains LLM invocation code for test-llm endpoint
- `app/models/settings.py` (90 LOC) — Settings singleton with 25+ unrelated fields in one model
- Services injected via `app.extensions["services"]` dict — no type safety

**Well-designed components (do not touch unless necessary):**

- PreFilter regex design (`app/services/prefilter.py`)
- VerdictParser Pydantic integration (`app/services/verdict_parser.py`)
- LogBuffer token estimation (`app/services/log_buffer.py`)
- LLMClient retry logic (`app/services/llm_client.py`)
- CLIBackendRunner semaphore (`app/services/cli_backends.py`)
- PromptTemplate versioning (`app/models/prompts.py`)

**Test suite:** 10 files, 31 tests, ~700 LOC. Estimated 40-50% coverage. Uses pytest with Flask app context fixtures. No integration tests for full pipeline.

## Constraints

- **API contract**: All existing endpoints in README must continue to work with identical request/response shapes
- **Test stability**: Existing 31 tests must pass throughout every phase
- **Tech stack**: Python 3.12, Flask, SQLAlchemy, Pydantic v2, SQLite, Docker, APScheduler — no new frameworks
- **Incremental delivery**: Each phase must be independently shippable
- **No new features**: Purely structural refactoring — same behavior, better architecture

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Refactor-only milestone (no features) | Clean foundation needed before React SPA, RAG, etc. Tech debt compounds | — Pending |
| Keep Flask (no FastAPI migration) | Working framework, minimize blast radius of refactor | — Pending |
| Alembic for migrations | Replace hardcoded SQL in app factory; industry standard for SQLAlchemy | — Pending |
| Repository pattern over raw queries | Testability, query optimization, single responsibility | — Pending |
| Pydantic v2 for request/response | Already in stack (VerdictParser); consistent validation approach | — Pending |
| Strategy pattern for alerts | Prep for ROADMAP Phase 3/5 multi-channel without building it now | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-04 after Phase 1 completion*
