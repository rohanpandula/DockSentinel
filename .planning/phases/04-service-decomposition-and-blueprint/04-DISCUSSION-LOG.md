# Phase 4: Service Decomposition and Blueprint - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-14
**Phase:** 04-service-decomposition-and-blueprint
**Areas discussed:** AlertService boundary, Web Blueprint layout, Endpoint name preservation, app/__init__.py slimming strategy
**Mode:** Recommendations-only (user directive: "go with recommendations")

**External skills consulted before recommendations:**
- `alirezarezvani/claude-skills` repo (`engineering-team/senior-backend/SKILL.md`, `engineering-team/senior-architect/SKILL.md`)
- senior-backend informed: per-resource blueprint pattern + minimal factory target (<50 LOC where possible)
- senior-architect: did not yield concrete mechanics for this extraction; project CLAUDE.md rules carried the remaining decisions

---

## AlertService boundary

| Option | Description | Selected |
|--------|-------------|----------|
| AlertService owns gating + formatting; Strategy is thin transport | AlertService takes cooldown + rate-limit + dedup queries + message formatting out of Sentinel. AlertStrategy.send(message, config) is a ~8 LOC wrapper. | ✓ |
| AlertService is a thin dispatcher; Sentinel keeps gating | Sentinel still runs cooldown/rate-limit; AlertService only formats + dispatches. | |
| AlertRateLimiter helper + AlertService dispatch | Split gating into a third class. | |

**User's choice:** First option (recommended)
**Notes:** Lets Slack/Discord slot in as one-class additions later; fully clears alert logic out of SentinelService (~30 LOC). TelegramNotifier stays as the low-level HTTP client; TelegramAlertStrategy wraps it.

---

## Web Blueprint layout

| Option | Description | Selected |
|--------|-------------|----------|
| Single `app/web/routes.py` Blueprint for all 8 handlers | Mirrors minimal-surface principle; short handlers share container-access/redirect patterns. | ✓ |
| Per-domain split (`app/web/dashboard.py`, `settings.py`, `exclusions.py`...) | Mirrors `app/api/` more closely; more files. | |
| Single Blueprint inside `app/web/__init__.py` package | Package marker + Blueprint in same file. | |

**User's choice:** First option (recommended)
**Notes:** Per-domain split would be premature abstraction at this size. CLAUDE.md rule: "three similar lines > one premature helper."

---

## Endpoint name preservation

| Option | Description | Selected |
|--------|-------------|----------|
| `url_prefix=""` + explicit `endpoint=` kwargs on every `@bp.route` | Templates and tests untouched; `url_for("dashboard")` resolves as before. | ✓ |
| Update all `url_for()` calls in 10+ template references to `web.endpoint_name` | Bigger blast radius; changes templates. | |
| Register routes without a Blueprint using `@app.route` in a helper | Simpler but keeps global app coupling; doesn't meet APP-01 spirit. | |

**User's choice:** First option (recommended)
**Notes:** APP-03 requires endpoint names preserved. Explicit `endpoint=` kwargs are the surgical fix.

---

## app/__init__.py slimming strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Extract web routes + service wiring (`composition.py`) + seed_defaults (`bootstrap.py`); keep `_ensure_sqlite_parent_dir` + `_register_blueprints` inline | Hits <100 LOC target; distributes concerns sensibly. | ✓ |
| Only extract web routes | Factory stays ~170 LOC; fails APP-02. | |
| Maximal split: also extract config loading + coordinator lifecycle | Over-splitting; factory becomes too sparse. | |

**User's choice:** First option (recommended)
**Notes:** Target `app/__init__.py` ≤ 90 LOC. `composition.py` ≈ 50 LOC, `bootstrap.py` ≈ 25 LOC, `app/web/routes.py` ≈ 180 LOC (handler bodies unchanged).

---

## Claude's Discretion

- Exact ordering inside `build_container()` (as long as dependency order holds)
- Internal helper method names inside `AlertService` beyond the locked `maybe_send`
- Whether `bootstrap.py` takes `db` as a parameter or imports from `app.extensions`
- Test injection approach for AlertService (monkeypatch vs. container swap — both work)

## Deferred Ideas

- Slack/Discord/email alert strategies — ROADMAP Phase 3 (Notification Center)
- SentinelService pipeline decomposition (PIPE-01/PIPE-02) — v2 requirements
- AlertService structured logging — Phase 5 (API Quality)
