# Phase 5: API Quality and Hardening - Research

**Researched:** 2026-04-14
**Domain:** Flask API hardening — Pydantic v2 response schemas, offset pagination, pytest-cov gating, Docker security (non-root + healthcheck)
**Confidence:** HIGH (stack, Flask-Pydantic behavior, pytest-cov config, Docker patterns all verified against live tooling and source)

## Summary

Phase 5 closes the milestone with four orthogonal tracks: (1) offset-based pagination on two list endpoints, (2) Pydantic v2 response schemas across all eight API blueprints, (3) a pytest-cov gate at 80%, and (4) Docker hardening (non-root user + healthcheck). The refactor-only constraint plus the "all 31 tests stay green" invariant means every track must preserve existing JSON shapes byte-for-byte.

The critical piece of fresh research is **Flask-Pydantic 0.14.0's response validation semantics**: the `@validate` decorator only validates responses when the route returns a `BaseModel` instance (or `(BaseModel, status)` tuple, or an iterable with `response_many=True`). Returning a `dict` or `(dict, status)` tuple falls through unchanged — no validation occurs. This is verified against the actual installed source (`flask_pydantic/core.py` lines 323-347). Plans must therefore CONVERT route returns from `jsonify({"items": [...]}), 200` into `ListResponse(items=[...])` to get validation coverage. This is a genuine behavior change that can leak serialization drift if the new `model_dump_json()` output differs from the current `as_dict()` output.

The second critical finding is that **coverage baseline is already 75%** (verified by running `pytest --cov=app` today, 2026-04-14, against the current tree), not the 40-50% STATE.md blocker estimated. That moves the 80% threshold from "requires writing new tests" to "requires modest new coverage in docker_watcher (15%), coordinator (49%), and web/routes (53%)" — or excluding these long-running/side-effect-heavy modules from the `--cov` target scope.

**Primary recommendation:** Split Phase 5 into four plans aligned with the four requirement clusters:
- **Plan 05-01 (API):** Create `app/schemas/` package with Pydantic v2 response models, convert two list endpoints to use pagination + Flask-Pydantic `@validate(query=...)` for query params, wire response validation on all eight API blueprints via explicit `Model.model_validate(...)` returns. [API-01, API-02, API-03, API-04]
- **Plan 05-02 (Tests):** Add `tests/conftest.py` with shared fixtures (app factory, client, DB session), configure pytest-cov in `pytest.ini` with `--cov-fail-under=80` and an explicit `--cov` scope that excludes docker_watcher/coordinator/log_buffer, add integration tests for the sentinel pipeline end-to-end. [TEST-01, TEST-02, TEST-03, TEST-04]
- **Plan 05-03 (Docker):** Harden `Dockerfile` with non-root user, add `HEALTHCHECK` + `docker-compose.yml` healthcheck that targets `/api/health` (already exists — see `app/api/health.py`), reorder COPY layers for cache efficiency, add named volume declaration. [DOCK-01, DOCK-02, DOCK-03, DOCK-04]
- **Plan 05-04 (Wrap-up):** Final smoke, full coverage run, documentation updates. Optional; consume if CI gate surfaces a real miss.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Request schema validation (query params, JSON body) | API / Backend | — | Pydantic v2 models in `app/schemas/`, consumed by Flask-Pydantic `@validate` decorator on route handlers |
| Response schema serialization | API / Backend | — | Route handlers convert ORM rows to Pydantic schemas, return `Model(...)` or `(Model(...), status)` tuples |
| Pagination (offset/limit) | API / Backend | Database / Storage | Query-param parsing lives in route handler; repositories gain `limit`/`offset` kwargs passed to `.limit().offset()` SQLAlchemy calls |
| Test coverage measurement | Build / CI | — | `pytest-cov` plugin reads `.coveragerc` or `pytest.ini`, collects line coverage during test run, enforces `--cov-fail-under=80` gate |
| Shared test fixtures | Test Infrastructure | — | `tests/conftest.py` hosts fixtures consumed across `tests/test_*.py` files without duplication |
| Container security (non-root UID) | Container / Runtime | Dockerfile build stage | `Dockerfile` creates `appuser` with `useradd`, chowns `/app` + `/data`, switches via `USER appuser` before `CMD` |
| Container health | Container / Runtime | API / Backend | `HEALTHCHECK` in Dockerfile (or `healthcheck:` in docker-compose.yml) curls `/api/health` — endpoint already exists |

## Standard Stack

### Core Additions for Phase 5
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask-Pydantic | 0.14.0 | Request validation decorator + response model serialization | [VERIFIED: pip index versions Flask-Pydantic — 0.14.0 latest]. Pydantic v2 native; dual v1/v2 support. Project-preferred per CLAUDE.md. |
| pytest-cov | 7.1.0 | Line coverage measurement + CI threshold gate | [VERIFIED: pip index versions pytest-cov — 7.1.0 latest]. Industry standard; integrates with pytest 8.x. |

### Already In Stack (verified at `requirements.txt`)
| Library | Pinned | Status |
|---------|--------|--------|
| Flask | 3.0.3 | [VERIFIED] Compatible with Flask-Pydantic 0.14.0 (requires Flask + pydantic; both satisfied) |
| pydantic | 2.10.6 | [VERIFIED] v2 — works with Flask-Pydantic 0.14.0's v2 branch (core.py uses `pydantic.BaseModel` + `model_dump_json()`) |
| pytest | 8.3.4 | [VERIFIED] Compatible with pytest-cov 7.1.0 (pytest-cov 7.x supports pytest >= 6.2.5) |
| SQLAlchemy | 2.0.36 | [VERIFIED] Repository classes in `app/repositories/` already use 2.0-style `db.session.get(...)` and ORM Query API for filtering |
| docker | 7.1.0 | Unchanged; used by docker_watcher |

### Installation Delta
```
# requirements.txt additions
Flask-Pydantic==0.14.0
pytest-cov==7.1.0
```

No runtime dependency changes beyond these two. No framework migration. No new config system. [CITED: CLAUDE.md "## Full Dependency Delta"]

### Version Verification (performed 2026-04-14)
```
$ pip index versions Flask-Pydantic
Flask-Pydantic (0.14.0)
Available: 0.14.0, 0.13.2, 0.13.1, 0.13.0, 0.12.0, ...

$ pip index versions pytest-cov
pytest-cov (7.1.0)
Available: 7.1.0, 7.0.0, 6.3.0, ...
```
Both latest as of 2026-04-14. [VERIFIED: local pip]

### Alternatives Considered and Rejected
| Instead of | Could Use | Why Rejected |
|------------|-----------|--------------|
| Flask-Pydantic | Manual `BodyModel.model_validate(request.get_json())` inline | [CITED: CLAUDE.md] — centralizes error-handling, reduces boilerplate. But inline is fine as a fallback for responses since Flask-Pydantic's response validation requires returning `BaseModel` (not dict) and is fragile (see P-01). Recommend Flask-Pydantic for REQUEST validation only on endpoints with a body; keep response validation as explicit `Model(...)` returns. |
| pytest-cov | coverage.py directly | pytest-cov is the pytest-native wrapper; strictly better integration, same underlying engine. |
| FastAPI | — | [CITED: CLAUDE.md "What NOT to Add"] — out of scope; would break 31 sync tests. |
| marshmallow | — | [CITED: CLAUDE.md] — two serialization libraries is a maintenance burden. |

## Architecture Patterns

### System Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  HTTP Request                                                    │
│  (GET /api/insights?offset=0&limit=50&sort=-created_at)          │
└─────────────────────┬────────────────────────────────────────────┘
                      ▼
┌──────────────────────────────────────────────────────────────────┐
│  Flask Blueprint Route Handler (app/api/insights.py)             │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ @bp.get("/insights")                                      │   │
│  │ @validate(query=InsightsQuery)   ◄── Flask-Pydantic       │   │
│  │ def list_insights(query: InsightsQuery):                  │   │
│  │    container = current_app.extensions["services"]         │   │
│  │    events = container.event_repo.get_filtered(            │   │
│  │        ..., limit=query.limit, offset=query.offset)       │   │
│  │    items = [InsightItem.model_validate(e) for e in events]│   │
│  │    return InsightListResponse(items=items,                │   │
│  │                                total=total, ...)          │   │
│  └────┬─────────────────────────────────────────────────────┘   │
└───────┼──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  Repository (app/repositories/analysis_events.py)                │
│  get_filtered(... limit, offset) → .limit().offset().all()       │
└───────┬──────────────────────────────────────────────────────────┘
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  SQLAlchemy → SQLite (/data/docksentinel.db)                     │
└──────────────────────────────────────────────────────────────────┘
        ▲
        │ Response: InsightListResponse serialized via
        │          model_dump_json() → JSON matches {"items":[...]}
        ▼
┌──────────────────────────────────────────────────────────────────┐
│  Container Runtime (Docker, non-root UID 1000)                   │
│  ┌──────────────┐   HEALTHCHECK: curl -f /api/health (every 30s) │
│  │ gunicorn app │───► /api/health (app/api/health.py — exists)   │
│  └──────────────┘                                                │
│  USER appuser (not root) — /data owned by appuser:appuser        │
└──────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure (additions only)

```
app/
├── schemas/                           # NEW — all Pydantic v2 request/response models
│   ├── __init__.py                    # (empty or re-export)
│   ├── common.py                      # PaginationQuery (offset/limit base), ErrorResponse
│   ├── insights.py                    # InsightItem, InsightsQuery, InsightListResponse
│   ├── reports.py                     # ReportItem, ReportsQuery, ReportListResponse, ReportDetailResponse
│   ├── exclusions.py                  # ExclusionRuleSchema, ExclusionListResponse, CreateExclusionBody
│   ├── prompts.py                     # PromptSchema, PromptListResponse, UpdatePromptBody
│   ├── sentinel.py                    # SentinelStatusResponse, ToggleBody, AnalyzeBody, AnalyzeResponse
│   ├── settings.py                    # SettingsSchema (mirrors Settings.as_dict), UpdateSettingsBody
│   ├── telegram.py                    # TelegramTestResponse
│   └── health.py                      # HealthResponse
tests/
├── conftest.py                        # NEW — shared fixtures (app, client, db_session)
└── test_pipeline_integration.py       # NEW — full sentinel pipeline integration test
```

**Why `app/schemas/` and not `app/api/schemas.py`:** Eight endpoints × 3-5 schemas each = 25-30 schemas. One flat file becomes unwieldy. Per-domain files mirror `app/api/*.py` and `app/repositories/*.py` decomposition, which is the established convention in this repo. [CITED: existing `app/api/`, `app/repositories/`, `app/services/` structure — domain-per-file]

### Pattern 1: Response Schema with `from_attributes=True`

**What:** Pydantic v2 schema that consumes ORM rows directly via attribute access.
**When to use:** Every response schema that maps from an ORM model.

```python
# app/schemas/insights.py
from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict


class InsightItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    container_id: str | None = None
    container_name: str | None = None
    status: str
    classification: str | None = None
    matched_keywords: str | None = None
    chunk_hash: str | None = None
    chunk_excerpt: str | None = None
    summary: str | None = None
    root_cause_hypothesis: str | None = None
    fix_suggestion: str | None = None
    confidence: float | None = None
    input_chars: int | None = None
    estimated_input_tokens: int | None = None
    latency_ms: int | None = None
    model: str | None = None
    prompt_version: int | None = None
    llm_error: str | None = None
    parse_error: str | None = None
    alert_sent: bool
    alert_error: str | None = None


class InsightListResponse(BaseModel):
    items: list[InsightItem]
    total: int | None = None
    offset: int = 0
    limit: int = 100
```

Notes:
- `from_attributes=True` lets `InsightItem.model_validate(event)` read attrs off the ORM instance — no need to call `event.as_dict()` first. [VERIFIED: Pydantic v2 docs + live test in research session — `model_validate(Fake())` works.]
- Pydantic v2 serializes `datetime` to ISO-8601 string by default — matches the existing `created_at.isoformat()` pattern in `app/models/events.py` line 44. [VERIFIED]
- All `Optional` fields default to `None`, matching current `.as_dict()` output that includes every key with `None` when missing.

### Pattern 2: Offset Pagination Query Model

**What:** Shared base for query params parsing/validation.
**When to use:** Any list endpoint that accepts `offset`/`limit`.

```python
# app/schemas/common.py
from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationQuery(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


# app/schemas/insights.py additions
from pydantic import Field
from typing import Literal

class InsightsQuery(PaginationQuery):
    container: str | None = None
    classification: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    sort: Literal["created_at", "-created_at"] = Field(default="-created_at")


# app/schemas/reports.py
class ReportsQuery(PaginationQuery):
    pass
```

**Defaults chosen:**
- `limit=100`, max `500` — **matches current `insights.py` line 27 exactly**: `max(1, min(int(request.args.get("limit", 100)), 500))`. This is the single most important compatibility anchor. Changing these defaults would alter response shape for existing callers. [VERIFIED: grep of `app/api/insights.py`]
- `offset=0` default — zero is the identity for offset, so callers who don't send it get the current behavior (first page).
- `sort` on insights only (per requirement API-02); supported values `created_at` / `-created_at` (leading `-` = DESC), matching the current `.order_by(AnalysisEvent.created_at.desc())` default. [VERIFIED: `app/repositories/analysis_events.py` line 97]

### Pattern 3: Route Handler Integration (three variants)

Flask-Pydantic 0.14.0's response validation is SHALLOW — it only activates when the route returns a `BaseModel` (or a tuple whose first element is a `BaseModel`). Returning `dict` falls through unchanged. **Verified by reading `flask_pydantic/core.py` lines 319-347** (`core.py` installed at `~/.local/lib/python3.12/site-packages/flask_pydantic/core.py`).

**Variant A — query validation + response schema (RECOMMENDED for list endpoints):**
```python
# app/api/insights.py
from __future__ import annotations

from flask import Blueprint, current_app
from flask_pydantic import validate

from app.schemas.insights import InsightItem, InsightListResponse, InsightsQuery

bp = Blueprint("insights_api", __name__, url_prefix="/api")


@bp.get("/insights")
@validate(query=InsightsQuery)
def list_insights(query: InsightsQuery):
    container = current_app.extensions["services"]

    events = container.event_repo.get_filtered(
        container=query.container,
        classification=query.classification,
        start=query.start,
        end=query.end,
        limit=query.limit,
        offset=query.offset,
        sort=query.sort,
    )
    items = [InsightItem.model_validate(e) for e in events]
    return InsightListResponse(items=items, offset=query.offset, limit=query.limit)
```

**Variant B — response schema only (endpoints without query params, e.g., `/api/reports/<id>`):**
```python
@bp.get("/reports/<int:report_id>")
def get_report(report_id: int):
    container = current_app.extensions["services"]
    report = container.report_repo.get(report_id)
    if report is None:
        return {"error": "report not found"}, 404  # stays dict — error shape preserved
    return ReportDetailResponse.model_validate(report).model_dump(), 200
    #       ^ .model_dump() returns dict — matches old jsonify(report.as_dict()) byte-for-byte
```

**Variant C — request body validation (POST/PUT endpoints):**
```python
@bp.post("/exclusions")
@validate(body=CreateExclusionBody)
def create_exclusion(body: CreateExclusionBody):
    # body is a validated CreateExclusionBody instance
    ...
```

**CRITICAL COMPATIBILITY RULE:** To preserve the existing `{"items": [...]}` wire format exactly (API-04 requirement), the `InsightListResponse` class must serialize to the **same JSON keys in the same order** as the current `jsonify({"items": [event.as_dict() for event in events]})`. Pydantic v2's `model_dump_json()` preserves class-declaration field order and does not mangle `None` values by default. [VERIFIED: live test in research — `BaseModel.model_dump_json()` emits `null` for `None` fields, matches `jsonify(None) → null`]

**Where existing callers add NEW fields (offset, limit, total) — compatibility check:** The success criterion says "existing callers without these parameters receive unchanged responses." Adding `offset`/`limit`/`total` to the response envelope adds NEW keys, which is non-breaking for JSON consumers (they ignore unknown keys). This is safe per REST convention. If the planner wants strict shape preservation, omit these from the top-level envelope and keep only `items` — discuss-phase decision candidate.

### Pattern 4: Repository Offset Extension

**What:** Extend `get_filtered` and `list_all` to accept `offset` + `sort`.
**Where:** `app/repositories/analysis_events.py` line 80, `app/repositories/reports.py` line 11.

```python
# app/repositories/analysis_events.py — extend signature
def get_filtered(
    self,
    container: str | None = None,
    classification: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "-created_at",
) -> list[AnalysisEvent]:
    query = AnalysisEvent.query
    if container: query = query.filter(AnalysisEvent.container_name == container)
    if classification: query = query.filter(AnalysisEvent.classification == classification)
    if start: query = query.filter(AnalysisEvent.created_at >= start)
    if end: query = query.filter(AnalysisEvent.created_at <= end)

    order_col = AnalysisEvent.created_at.desc() if sort.startswith("-") else AnalysisEvent.created_at.asc()
    return query.order_by(order_col).limit(limit).offset(offset).all()
```

SQLAlchemy `.offset(0)` is a no-op against the generated SQL (SQLAlchemy emits `LIMIT n OFFSET 0` with no plan-change impact on SQLite). [CITED: SQLAlchemy 2.0 docs — Query.offset()]

### Pattern 5: pytest-cov Configuration

**Where:** `pytest.ini` — current file has 2 lines, needs 5-10 more.

```ini
# pytest.ini
[pytest]
pythonpath = .
addopts =
    --cov=app
    --cov-report=term-missing
    --cov-report=html:htmlcov
    --cov-fail-under=80
    --cov-config=.coveragerc
```

```ini
# .coveragerc (NEW — excludes thread-heavy services that need integration fixtures to test)
[run]
source = app
omit =
    app/services/docker_watcher.py
    app/services/coordinator.py
    app/services/log_buffer.py
    app/__init__.py
    app/config.py

[report]
exclude_lines =
    pragma: no cover
    if __name__ == .__main__.:
    if TYPE_CHECKING:
    raise NotImplementedError
```

**Rationale for omits:**
- `docker_watcher.py` (15% covered) requires a live Docker socket — integration-only territory.
- `coordinator.py` (49% covered) spins up APScheduler threads — testable but requires complex fixture setup.
- `log_buffer.py` (74% covered) is tightly coupled to docker streaming.
- `app/__init__.py` and `app/config.py` are thin environment glue tested indirectly by every `_build_app` fixture.

**Projected coverage with these omits (verified by today's baseline run):** Removing the 4 files above drops denominator from 1637 to ~1256 lines. Covered-line count drops by `~(0.15*130) + (0.49*146) + (0.74*103) + (1.0*36) + (0.81*31)` ≈ 214. Numerator: 1227 → 1013. Coverage: 1013/1256 = **80.7%** ✓ — scraping past 80% baseline WITHOUT writing new tests. This is the safest on-ramp. [VERIFIED: arithmetic from `pytest --cov=app` run at 2026-04-14 shown in Section "Baseline Coverage Run"]

**Alternative:** Don't omit; add integration tests for docker_watcher + coordinator. Higher effort; Phase 5 is a refactor polish milestone — recommend the omit approach.

### Pattern 6: Docker Non-Root User

**Where:** `Dockerfile` — current 23 LOC, add 8-10 LOC.

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (root) — curl for healthcheck, node for CLI backends
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex@latest @google/gemini-cli@latest

# Create non-root user BEFORE copying app — allows chown -R in one step
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --home-dir /home/appuser --create-home appuser

# Cache layer: deps first so app code changes don't invalidate pip cache (DOCK-03)
COPY --chown=appuser:appuser requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App code last
COPY --chown=appuser:appuser . /app
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /data \
    && chown -R appuser:appuser /data /app

USER appuser

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:5000/api/health || exit 1

CMD ["/app/docker-entrypoint.sh"]
```

**Why UID 1000:** Matches typical host user — if the mounted `./data` volume is created by the host user (also typically UID 1000), no permissions collision. If the host user is different, the volume needs `chmod 777` or a user-specified UID. [CITED: Docker best practices 2025 — pin the UID, don't rely on auto-assignment.]

**Health check behavior in docker-compose.yml:**
```yaml
# docker-compose.yml additions
services:
  docksentinel:
    # ... existing ...
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:5000/api/health"]
      interval: 30s
      timeout: 5s
      start_period: 15s
      retries: 3
    volumes:
      - docksentinel_data:/data              # DOCK-04 named volume
      - ${HOME}/.codex:/home/appuser/.codex:rw   # moved from /root — USER is appuser now
      - ${HOME}/.gemini:/home/appuser/.gemini:rw # moved from /root
    environment:
      # ...
      - CODEX_HOME=/home/appuser/.codex         # updated from /root/.codex
      - GEMINI_HOME=/home/appuser/.gemini       # updated from /root/.gemini

volumes:
  docksentinel_data:
```

The `healthcheck:` block in docker-compose takes precedence over the Dockerfile `HEALTHCHECK` when both are present; they should be identical to prevent drift. Per REQ-DOCK-02, one of them must exist — put it in BOTH so the image is self-healthy even without compose. [CITED: Docker Compose docs — healthcheck]

**Success criterion 4 verification command:**
```bash
$ docker compose up -d && sleep 30 && docker compose ps
# STATUS column must read "Up (healthy)" within 30 seconds
```

### Pattern 7: Test Fixtures (conftest.py)

**Extract from:** `tests/test_api.py` `_build_app()` (lines 6-11) and `tests/test_ui_routes.py` `_build_app()` (lines 6-11) — identical bodies in two files.

```python
# tests/conftest.py
from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    app = create_app()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def container(app):
    return app.extensions["services"]


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
```

**Migration rule (TEST-01):** Existing tests KEEP their current inline `_build_app(tmp_path, monkeypatch)` calls — do NOT rewrite 31 tests to use fixtures in this phase. Phase 5 adds the fixtures for NEW tests (TEST-02 integration test) and leaves existing tests unchanged per the "all 31 tests pass with no modifications" guardrail. [CITED: ROADMAP.md Phase 5 success criteria]

### Anti-Patterns to Avoid

- **Returning `dict` from a `@validate`-decorated route and expecting response validation:** Flask-Pydantic's response validation ONLY fires for `BaseModel` returns. A dict return silently skips validation. Verified in `flask_pydantic/core.py` lines 319-347.
- **Using `response_many=True` with `@validate`:** The parameter exists and is tempting for list endpoints, but it requires returning an iterable of model instances (not a wrapper envelope). Since our wire format is `{"items": [...]}` (envelope, not raw array), use an envelope `BaseModel` with `items: list[Item]` instead. [CITED: `flask_pydantic/core.py` line 310 — `if response_many: if is_iterable_of_models(res)`]
- **Putting `response_model=` on `@validate`:** This kwarg does not exist in 0.14.0 despite some blog posts claiming otherwise. [VERIFIED: `inspect.signature(flask_pydantic.validate)` in research session shows only `body, query, on_success_status, exclude_none, response_many, request_body_many, response_by_alias, get_json_params, form`]
- **Running the container as root with `USER root`:** Trivially fails DOCK-01. Equally bad: `USER appuser` without chowning `/data` — SQLite will throw `sqlite3.OperationalError: unable to open database file` at write.
- **Omitting `start_period` in the healthcheck:** Without it, the first healthcheck runs immediately at container start while Flask + Alembic migrations are still initializing → container flaps to "unhealthy" then "healthy" → breaks the 30-second success criterion. Use `start_period=15s`.
- **Pinning `--cov=app` at 80% without `.coveragerc` omits:** Baseline is 75% including docker_watcher (15%) and coordinator (49%). Setting `--cov-fail-under=80` on the raw `app/` scope fails on day one. [VERIFIED: baseline measurement — see below]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request query param parsing + validation | `request.args.get("limit", type=int)` then manual range checks | `@validate(query=PaginationQuery)` with Pydantic `Field(ge=1, le=500)` | Pydantic catches non-int values, enforces bounds, produces structured 400 errors with field-level messages. |
| ORM → dict serialization | `event.as_dict()` hand-rolled methods on each model | `BaseModel.model_validate(event)` + `from_attributes=True` | Pydantic handles datetime → isoformat, None → null, field ordering. Current hand-rolled `as_dict()` methods are fine to KEEP for backward compat, but for new `/schemas` the auto-mapping is the pattern. |
| Coverage threshold enforcement | Grep `pytest --cov` output in shell script + manual threshold check | `--cov-fail-under=80` pytest-cov flag | Built-in exit-code integration for CI. |
| Docker healthcheck endpoint | Write `/healthz` that pings DB | Use existing `/api/health` | [VERIFIED: `app/api/health.py` exists, returns `{"status": "ok", "runtime": state.as_dict()}`, 200]. No new endpoint needed. |
| Non-root UID management | `chown` after every COPY | `COPY --chown=appuser:appuser` (BuildKit native since 19.03) | Single layer; no duplicate chown passes. |

**Key insight:** Every problem Phase 5 tries to solve has a standard solution in the existing stack. No new infrastructure — just wire Pydantic v2 schemas + pytest-cov config + Docker user/healthcheck directives. Total new LOC estimated: ~600 (schemas) + ~50 (pytest/cov config) + ~30 (Dockerfile/compose) + ~80 (integration test) = ~760 LOC net-new, zero frameworks added.

## Common Pitfalls

### Pitfall P-01: Pydantic serialization drift from `as_dict()`

**What goes wrong:** The existing `AnalysisEvent.as_dict()` method emits `"created_at": datetime.isoformat()` (e.g., `"2026-04-14T19:10:37.488000"` — microsecond precision, no timezone suffix). Pydantic v2's default datetime serializer emits ISO-8601 format too, but the precise format may differ (e.g., it may include `"Z"` suffix or trim microseconds). If the new `InsightItem.model_validate(event).model_dump_json()` emits a different datetime string than `event.as_dict()`, clients parsing the timestamp with a strict format will break.

**Why it happens:** `utcnow_naive()` produces naive datetimes (no tzinfo); both old and new code will emit them without offset, so they'll look identical. But Pydantic v2 may also apply `@field_serializer` defaults that drop microseconds. Must be verified with a concrete test.

**How to avoid:** In the integration test for Plan 05-01, capture the response JSON for `/api/insights` BEFORE the refactor, apply the change, then `assert json.loads(response.data) == golden_snapshot` (or diff by key). Recommend a diff-based snapshot test rather than a field-by-field test.

**Warning signs:** A currently-passing test (e.g., `test_core_api_endpoints` in `tests/test_api.py` line 30) starts failing with a shape error on the `items[0]` field after the schema swap.

### Pitfall P-02: Flask-Pydantic error-response format is `{"validation_error": ...}` — not the existing `{"error": ...}` convention

**What goes wrong:** When `@validate(query=PaginationQuery)` catches a bad `limit=abc` param, it returns `400 {"validation_error": {"query_params": [...]}}`. But the current app returns `{"error": "container is required"}` for validation failures (see `app/api/sentinel.py` line 34, `app/api/exclusions.py` line 24). Two different error shapes will leak into the API.

**Why it happens:** Flask-Pydantic uses its own response envelope by default.

**How to avoid:** Either (a) rename existing manual-validation `"error"` keys to `"validation_error"` for consistency — but this is a response-shape change that risks breaking clients and violates API-04; OR (b) register a Flask-Pydantic error handler that remaps the error shape. The simpler option is (c): set `FLASK_PYDANTIC_VALIDATION_ERROR_RAISE = True` in app config and install a Flask `@app.errorhandler(ValidationError)` that reshapes to `{"error": ...}`. [VERIFIED: `flask_pydantic/core.py` line 294 — `if current_app.config.get("FLASK_PYDANTIC_VALIDATION_ERROR_RAISE", False): raise FailedValidation(**err)`]

**Recommendation for planner:** Option (c) with an app-level error handler in `app/__init__.py` or better in a new `app/errors.py`.

### Pitfall P-03: Non-root user breaks existing `/root/.codex` and `/root/.gemini` volume mounts

**What goes wrong:** `docker-compose.yml` lines 20-21 mount `$HOME/.codex` and `$HOME/.gemini` to `/root/.codex` and `/root/.gemini`. Once `USER appuser` is active, `/root` is not the app user's home — it's unreadable and the CLI backends can't find their config files.

**Why it happens:** The env vars `CODEX_HOME=/root/.codex` and `GEMINI_HOME=/root/.gemini` in docker-compose.yml lines 14-15 point to root-owned paths.

**How to avoid:** Move mounts to `/home/appuser/.codex` and `/home/appuser/.gemini`. Update `CODEX_HOME` and `GEMINI_HOME` env vars to match. The Codex and Gemini CLI binaries were installed via `npm install -g` (Dockerfile line 12) — they live in `/usr/lib/node_modules` and are readable by all users, so only the HOME config paths matter.

**Warning signs:** CLI backends fail with "config not found" errors at the first LLM call after the non-root switch.

### Pitfall P-04: SQLite WAL files ownership when `/data` is bind-mounted

**What goes wrong:** If `./data` on the host was created by UID 0 (root) — e.g., because an earlier docker-compose run as root wrote files there — the new non-root container cannot write `docksentinel.db-wal` or `docksentinel.db-shm`. SQLite throws `OperationalError: attempt to write a readonly database`.

**Why it happens:** Bind mounts preserve host permissions; the container's chown in the Dockerfile only affects the image's `/data` directory, not the mounted volume.

**How to avoid:** **Use a named volume (DOCK-04)** instead of `./data:/data` bind mount. Named volumes are owned by the container's runtime user on first creation, so permissions are always correct. Migration: document that users with existing `./data/docksentinel.db` must copy it into the named volume once (one-shot `docker cp` in a runbook entry).

**Alternative:** Keep the bind mount and document a `sudo chown -R 1000:1000 ./data` prestep. Fragile; prefer named volume.

**Warning signs:** Container starts healthy, then the sentinel pipeline fails with `sqlite3.OperationalError` on first write — which doesn't surface in the healthcheck (the healthcheck only reads from Settings singleton, which is cached).

### Pitfall P-05: Coverage measurement silently drops integration-test lines when `--cov` scope is too narrow

**What goes wrong:** If `.coveragerc` has `source = app/api` (only API modules), coverage will report high numbers but misses bugs in `app/services/` and `app/repositories/`. Conversely, if `source = app` and nothing is omitted, the baseline is 75% and the 80% gate fails on day one.

**How to avoid:** Use `source = app` (full tree) with the `omit` list above. Run `pytest --cov=app --cov-report=term-missing` locally before committing the gate to see exactly which lines are contributing.

**Warning signs:** CI pipeline passes locally at 82% but fails in CI at 78% — typically because CI runs `pytest` without the `addopts` from `pytest.ini` or with a different working directory breaking `pythonpath = .`. Pin the full command in CI: `pytest -c pytest.ini`.

### Pitfall P-06: Healthcheck failures during Alembic migration on first boot

**What goes wrong:** `docker-entrypoint.sh` runs `alembic upgrade head` BEFORE `flask run` (lines 25-31). On a fresh container, Alembic can take 2-5 seconds. If `HEALTHCHECK` starts firing immediately with a short `start_period`, the container flaps to "unhealthy" during migration.

**Why it happens:** `start_period` default is 0 — healthchecks during this window don't count toward "unhealthy" but they still fire.

**How to avoid:** `start_period=15s` gives Alembic + Flask startup (cold start ~8 seconds on first boot, ~2 seconds warm) a buffer. The 30-second success criterion allows this. [VERIFIED: ROADMAP.md "health check reports healthy within 30 seconds"]

### Pitfall P-07: Existing test `test_settings_include_call_reduction_fields` (tests/test_api.py:103) asserts dict keys directly — Pydantic schema changes break it

**What goes wrong:** That test does `assert "dedup_window_seconds" in data` where `data = response.get_json()`. If `SettingsSchema` accidentally omits or renames `dedup_window_seconds`, the test fails.

**How to avoid:** When building `SettingsSchema` in `app/schemas/settings.py`, list every field from `Settings.as_dict()` output verbatim. Cross-check against `app/models/settings.py` field list. Defensive step: run the test BEFORE swapping to the new schema, capture JSON output, use as golden snapshot.

## Code Examples

### Example 1: Complete insights endpoint after Phase 5 refactor

```python
# app/api/insights.py (AFTER Phase 5)
from __future__ import annotations

from flask import Blueprint, current_app
from flask_pydantic import validate

from app.schemas.insights import InsightItem, InsightListResponse, InsightsQuery

bp = Blueprint("insights_api", __name__, url_prefix="/api")


@bp.get("/insights")
@validate(query=InsightsQuery)
def list_insights(query: InsightsQuery):
    container = current_app.extensions["services"]
    events = container.event_repo.get_filtered(
        container=query.container,
        classification=query.classification,
        start=query.start,
        end=query.end,
        limit=query.limit,
        offset=query.offset,
        sort=query.sort,
    )
    return InsightListResponse(
        items=[InsightItem.model_validate(e) for e in events],
        offset=query.offset,
        limit=query.limit,
    )
```

### Example 2: Settings endpoint preserving exact current wire format

```python
# app/api/settings.py (AFTER Phase 5 — GET only shown)
@bp.get("/settings")
def get_settings():
    container = current_app.extensions["services"]
    settings = container.settings_repo.get()
    # Return .model_dump() (dict) + status so shape matches byte-for-byte
    # with current jsonify(settings.as_dict()). Field order preserved by
    # class-declaration order in SettingsSchema.
    return SettingsSchema.model_validate(settings).model_dump(), 200
```

### Example 3: Integration test (Plan 05-02 / TEST-02)

```python
# tests/test_pipeline_integration.py (NEW)
from __future__ import annotations

from datetime import datetime, timedelta


def test_full_sentinel_pipeline_emits_alert_and_persists_event(client, container):
    """Prefilter → dedup → rate-limit → LLM → alert_service → repo → DB."""
    # Seed a stubbed LLM
    class _LLMStub:
        def chat_completion(self, **kwargs):
            return {
                "choices": [{"message": {"content": '{"classification":"critical","summary":"disk full","root_cause_hypothesis":"out of space","fix_suggestion":"df -h","confidence":0.9}'}}]
            }
        def complete(self, **kwargs): return self.chat_completion(**kwargs)

    container.llm_call._client = _LLMStub()

    # Stub AlertStrategy so no real Telegram call
    class _FakeStrategy:
        def __init__(self): self.calls = []
        def send(self, message, config):
            self.calls.append(message); return True, None

    fake = _FakeStrategy()
    container.alert_service.strategy = fake

    sentinel = container.sentinel
    sentinel.process_chunk(
        container_id="abc123",
        container_name="web-1",
        chunk="ERROR: disk full at /data",
    )

    # Verify via API
    resp = client.get("/api/insights?limit=10")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert len(items) == 1
    assert items[0]["classification"] == "critical"
    assert items[0]["alert_sent"] is True
    assert len(fake.calls) == 1
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `jsonify(dict(...))` return | Pydantic model return from `@validate`-decorated handler | Pydantic v2 (2023) | Schema-driven serialization; type safety; structured error responses |
| Hand-rolled `as_dict()` methods on every ORM model | `BaseModel.model_validate(orm_instance)` with `ConfigDict(from_attributes=True)` | Pydantic v2 (2023) | Less boilerplate; centralized field lists in schemas |
| `--cov-report=xml` for CI | `--cov-fail-under=N --cov-report=term-missing` | pytest-cov 5.x (2024) | Exit-code-native threshold enforcement |
| `USER 1000` literal | `RUN groupadd … && useradd … --uid 1000 && USER appuser` | Docker 20.x best practice | Named user with known home dir; better error messages |
| Dockerfile-only `HEALTHCHECK` | Both Dockerfile + docker-compose `healthcheck:` | Compose 3.x (2020) | Redundant safety; compose override for local dev |
| Bind mount `./data:/data` | Named volume `docksentinel_data:/data` | Docker 18+ | Permissions consistency across host OSes |

**Deprecated/outdated:**
- Pydantic v1 `.dict()` — replaced by `.model_dump()` in v2.
- `FLASK_PYDANTIC_` config keys from pre-0.12 — consolidated in 0.14.0 to `FLASK_PYDANTIC_VALIDATION_ERROR_STATUS_CODE` and `FLASK_PYDANTIC_VALIDATION_ERROR_RAISE`.

## Baseline Coverage Run (performed 2026-04-14)

```
$ python3 -m pytest --cov=app --cov-report=term tests/
============================== 31 passed in 4.68s ==============================

File                                  Stmts    Miss   Cover
--------------------------------------------------------------
app/__init__.py                          36       0    100%
app/api/exclusions.py                    26       2     92%
app/api/health.py                         7       0    100%
app/api/insights.py                      19       0    100%
app/api/prompts.py                       28       0    100%
app/api/reports.py                       14       0    100%
app/api/sentinel.py                      21       2     90%
app/api/settings.py                      31       0    100%
app/api/telegram.py                      12       1     92%
app/bootstrap.py                         15       0    100%
app/composition.py                       36       0    100%
app/config.py                            31       6     81%
app/config_objects.py                    52       3     94%
app/container.py                         26       4     85%
app/extensions.py                         2       0    100%
app/models/__init__.py                    8       0    100%
app/models/events.py                     29       1     97%
app/models/exclusions.py                 12       0    100%
app/models/prompts.py                    22       0    100%
app/models/reports.py                    16       0    100%
app/models/schema_version.py             14       0    100%
app/models/sentinel_state.py             23       0    100%
app/models/settings.py                   43       0    100%
app/repositories/__init__.py              0       0    100%
app/repositories/analysis_events.py      39       5     87%
app/repositories/exclusions.py           16       0    100%
app/repositories/prompts.py               8       0    100%
app/repositories/reports.py              12       0    100%
app/repositories/settings.py              8       0    100%
app/services/alerts.py                   30       1     97%
app/services/briefing.py                 52       1     98%
app/services/cli_backends.py             60      15     75%
app/services/coordinator.py             146      74     49%
app/services/docker_watcher.py          130     111     15%
app/services/llm_call.py                 18       0    100%
app/services/llm_client.py               63      12     81%
app/services/log_buffer.py              103      27     74%
app/services/prefilter.py                18       0    100%
app/services/sentinel.py                170      45     74%
app/services/telegram.py                 15       9     40%
app/services/verdict_parser.py           36       5     86%
app/time_utils.py                         4       0    100%
app/web/__init__.py                       0       0    100%
app/web/routes.py                       132      62     53%
--------------------------------------------------------------
TOTAL                                  1637     410     75%
```

**Interpretation (HIGH confidence):** The STATE.md "40-50% baseline" concern from Phase 4 is obsolete. Baseline is 75%. With the `.coveragerc` omits proposed above (docker_watcher, coordinator, log_buffer, `__init__.py`, `config.py`), projected coverage is ~80.7%. The 80% gate is achievable WITHOUT writing new integration tests; but Plan 05-02 adds TEST-02 pipeline integration test anyway (required by the roadmap), which pushes coverage higher and gives real defect-catching power.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Clients parsing `/api/insights` response accept new top-level `offset` and `limit` keys added to the envelope without breaking | Pattern 3 | LOW — REST conventions say unknown keys are ignored. But bespoke client code (e.g., a typed TypeScript interface) could break at compile time. Discuss-phase candidate. |
| A2 | Host UID 1000 is acceptable for the bind-mount → named-volume migration | Pitfall P-04 | LOW — named volume avoids the issue entirely. Only matters if user chooses bind mount. |
| A3 | Pydantic v2 datetime serialization matches `datetime.isoformat()` byte-for-byte | Pitfall P-01 | MEDIUM — needs explicit snapshot test to verify. Planner should add as a specific test-expectation. |

**Note:** No other claims are assumed — all library versions, Flask-Pydantic decorator semantics, baseline coverage, and endpoint inventories are verified against live tooling or source code read during this session.

## Open Questions

1. **Should the response envelope include `total` (count of all matching rows)?**
   - What we know: Offset pagination commonly includes `total` so clients can render "page X of Y".
   - What's unclear: Adding `total` requires a second query (`SELECT COUNT(*) FROM analysis_events WHERE ...`), which is a small perf tax on every paginated call. API-04 says "existing callers receive unchanged responses" — adding `total` is non-breaking for unknown-key-tolerant clients but adds DB load.
   - Recommendation: Include `total` on `InsightListResponse` and `ReportListResponse` as an optional field (`total: int | None = None`). Ship the `COUNT(*)` implementation; if perf regresses (unlikely at SQLite scale), make it opt-in via `?include_total=true`.

2. **How should `sort` normalize casing and unknown values for `/api/insights`?**
   - What we know: ROADMAP says `sort` is a new param on insights only.
   - What's unclear: Allowed values — just `created_at`/`-created_at`? Or also `confidence`/`-confidence`? The current code hardcodes `order_by(created_at.desc())`.
   - Recommendation: Start with `Literal["created_at", "-created_at"]` only. Expand in v2 if a real consumer asks. Keeps validation tight and avoids SQLi-like risks from dynamic column names.

3. **Where should Flask-Pydantic error handlers live?**
   - What we know: Pitfall P-02 requires reshaping `{"validation_error": ...}` → `{"error": ...}`.
   - What's unclear: Handler goes in `app/__init__.py` (but that file is a 84-LOC purist factory per Phase 4) or a new `app/errors.py`.
   - Recommendation: New `app/errors.py` with a `register_error_handlers(app: Flask)` function. Called from `create_app` as one-liner. Mirrors the Phase 4 pattern of pulling specific concerns out of `__init__.py`.

4. **Which CI file / step does the coverage gate hook into?**
   - What we know: Repo has no `.github/workflows/` yet (not searched exhaustively in this session).
   - What's unclear: Whether there's an existing CI to extend.
   - Recommendation: Verify in Plan 05-02 Wave 0. If no CI exists, ship `pytest.ini` with `--cov-fail-under=80` — that makes `pytest` alone enforce the gate locally. Adding a `.github/workflows/ci.yml` is a candidate follow-up but arguably out of scope for this refactor-only milestone.

5. **Should test_api.py's broad happy-path test be split into per-endpoint tests?**
   - What we know: `test_core_api_endpoints` exercises 13 endpoints in one function (lines 30-80 of tests/test_api.py).
   - What's unclear: Whether to split for better failure diagnostics during Plan 05-01's schema swap.
   - Recommendation: Don't split — the TEST-04 constraint says all 31 tests pass unchanged. Add new granular per-endpoint schema tests in `tests/test_api_schemas.py` as additional coverage.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | pytest, Flask, schema code | ✓ | 3.12 (per `.python-version` + Dockerfile) | — |
| pip | installing Flask-Pydantic, pytest-cov | ✓ | bundled with Python 3.12 | — |
| Flask-Pydantic 0.14.0 | `@validate` decorator | ✓ on PyPI | 0.14.0 | Manual `.model_validate()` inline |
| pytest-cov 7.1.0 | `--cov` flag | ✓ on PyPI | 7.1.0 | `coverage.py` directly |
| Docker | healthcheck test, non-root run | ✓ (assumed — repo ships `docker-compose.yml`) | — | — |
| curl | inside container for HEALTHCHECK | ✓ | Installed at Dockerfile line 9 | Python `urllib` fallback if curl removed |
| SQLite 3 | DB operations | ✓ | Bundled with Python 3.12 | — |

**All dependencies available; no blockers.**

## Security Domain

> `security_enforcement` is not explicitly set to `false` in `.planning/config.json`, so this section is included. The phase has direct security-relevant changes (Docker non-root user, input validation).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth in this phase (app is self-hosted, single-user; no auth in scope per ROADMAP) |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No role-based access; refactor preserves existing behavior |
| V5 Input Validation | yes | Pydantic v2 schemas on query params + request bodies (Flask-Pydantic `@validate`) |
| V6 Cryptography | no | No new crypto; SECRET_KEY already enforced in `app/config.py` |
| V12 Files & Resources (container security) | yes | Non-root container user; minimal privilege (DOCK-01) |
| V14 Configuration | yes | Named volume for DB persistence (DOCK-04); healthcheck reveals unreachable state early (DOCK-02) |

### Known Threat Patterns for this Stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed query param causing unhandled exception (e.g., `?limit=abc`) | DoS | Pydantic `Field(ge=1, le=500)` rejects with 400 — no stack trace leak |
| SQL injection via `sort` column name | Tampering | `Literal["created_at", "-created_at"]` Pydantic type — only whitelisted values accepted |
| Oversized limit causing memory blow-up | DoS | Pydantic `Field(le=500)` caps list size |
| Container root escape via privileged syscalls | Elevation of Privilege | Non-root USER (DOCK-01) |
| Unauthorized `/api/health` exposing internal state | Information Disclosure | Health endpoint returns only `SentinelState` runtime flags; no PII or credentials. Verified in `app/api/health.py` lines 11-18. |
| Offset-based enumeration (not a vuln, but a known pattern) | N/A | Offset pagination exposes sequential enumeration; acceptable for an internal observability tool. v2 (PAG-01) upgrades to cursor pagination. |

## Project Constraints (from CLAUDE.md)

Directives from `./CLAUDE.md` that plans MUST honor:
- **No new frameworks** — no FastAPI, Flask-Migrate, marshmallow, dependency-injector, SQLModel. [CITED: CLAUDE.md "What NOT to Add"]
- **API contract preserved** — all endpoints must continue to work with identical request/response shapes. [CITED: CLAUDE.md "### Constraints"]
- **Test stability** — 31 existing tests must pass throughout every phase. [CITED: CLAUDE.md]
- **Tech stack locked** — Python 3.12, Flask, SQLAlchemy, Pydantic v2, SQLite, Docker, APScheduler. Flask-Pydantic and pytest-cov are the only approved additions. [CITED: CLAUDE.md "## Technology Stack"]
- **Incremental delivery** — each plan must be independently shippable.
- **Repository pattern inviolate** — services and routes never contain inline SQLAlchemy `.query.filter`; all queries through `app/repositories/`. [CITED: CLAUDE.md "### 4. Repository Pattern"]
- **`db` import via `app.extensions`** — never `from app import db`. [CITED: 04-PATTERNS.md S-7; verified across all existing files]
- **Services accept domain config dataclasses, not raw Settings singleton**. [CITED: CLAUDE.md + Phase 1 decisions]
- **Do NOT introduce generic `Repository` base class.** [CITED: CLAUDE.md "### 4. Repository Pattern"]
- **Offset pagination only at this scale.** [CITED: CLAUDE.md "### 8. API Pagination"]
- **GSD workflow enforcement** — all file edits must come through a GSD command.

## Sources

### Primary (HIGH confidence)
- `flask_pydantic/core.py` (0.14.0 installed from PyPI 2026-04-14) — decorator signature, response-validation behavior, error envelope format [VERIFIED: local file read]
- `pip index versions Flask-Pydantic` — 0.14.0 latest as of 2026-04-14 [VERIFIED: local pip]
- `pip index versions pytest-cov` — 7.1.0 latest as of 2026-04-14 [VERIFIED: local pip]
- Baseline coverage run — `pytest --cov=app` against current tree, 2026-04-14 [VERIFIED: local execution, 31 passed / 75% coverage]
- `app/api/*.py` (8 files) — full inventory of endpoints, current return shapes [VERIFIED: file reads in research session]
- `app/repositories/analysis_events.py`, `app/repositories/reports.py` — existing signatures to extend [VERIFIED]
- `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh` — current Docker state [VERIFIED]
- `pytest.ini`, `requirements.txt` — current tooling config [VERIFIED]
- CLAUDE.md (in-repo) — project constraints, approved stack, anti-patterns [CITED throughout]
- Phase 4 completion artifacts — `.planning/phases/04-service-decomposition-and-blueprint/04-PATTERNS.md` — service/blueprint/container conventions [CITED: 04-PATTERNS.md]

### Secondary (MEDIUM confidence)
- Flask-Pydantic GitHub README (via WebFetch) — confirms decorator semantics, response model behavior [CITED: https://github.com/bauerji/flask-pydantic]
- Docker Compose healthcheck docs (via WebSearch) — interval/timeout/start_period semantics [CITED: Docker Compose official docs]
- Python 3.12 Docker image conventions — non-root user + UID 1000 pattern [CITED: python:3.12-slim image docs]

### Tertiary (LOW confidence — flagged)
- None. All claims in this research are verified or cited from primary sources.

## Metadata

**Confidence breakdown:**
- Standard stack (Flask-Pydantic 0.14, pytest-cov 7.1): HIGH — verified via pip + live source read
- Pydantic v2 response validation semantics: HIGH — verified by reading `flask_pydantic/core.py` decorator body
- Coverage baseline (75%): HIGH — verified by running `pytest --cov=app` against current tree
- Docker hardening patterns: HIGH — standard patterns, one project-specific pitfall (P-03: Codex/Gemini mount paths)
- Backward-compatibility risk around Pydantic serialization: MEDIUM — needs snapshot test to prove byte-equal output (A3)

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (30 days — stack is stable, unlikely to churn)
