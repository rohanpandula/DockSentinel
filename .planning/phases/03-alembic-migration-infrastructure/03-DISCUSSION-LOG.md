# Phase 3: Alembic Migration Infrastructure - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-05
**Phase:** 03-alembic-migration-infrastructure
**Areas discussed:** Alembic configuration, Initial migration strategy, Schema compat replacement, Test environment strategy
**Mode:** Auto (recommended defaults selected)

---

## Alembic Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| render_as_batch=True with Flask-SQLAlchemy integration | Standard SQLite-compatible setup per CLAUDE.md guidance | ✓ |
| Plain Alembic without batch mode | Would fail on SQLite ALTER TABLE operations | |

**User's choice:** render_as_batch=True (auto-selected recommended)
**Notes:** MIG-01 explicitly requires batch mode. CLAUDE.md references Alembic batch migration docs.

---

## Initial Migration Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Autogenerate from models + stamp existing DBs | Captures full schema, stamps v0.2 databases | ✓ |
| Manual migration writing | Error-prone for 7 tables with complex columns | |
| Skip baseline, only write forward migrations | Loses schema history | |

**User's choice:** Autogenerate + stamp (auto-selected recommended)
**Notes:** MIG-02 requires stamp head for existing databases.

---

## Schema Compat Replacement

| Option | Description | Selected |
|--------|-------------|----------|
| Single revision with batch_alter_table for all 8 columns | One logical change = one revision | ✓ |
| One revision per column | Granular but creates 8 revisions for one logical change | |
| Fold into initial migration | Would make initial migration non-idempotent for existing DBs | |

**User's choice:** Single revision (auto-selected recommended)
**Notes:** All 8 columns were added in one logical change (CLI backend support + call reduction settings).

---

## Test Environment Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| db.create_all() gated behind TESTING=True | Tests stay fast, production uses Alembic | ✓ |
| Always use Alembic (tests run migrations) | Slower tests, tighter prod parity | |
| Separate test DB setup script | Additional complexity for no clear benefit | |

**User's choice:** TESTING gate (auto-selected recommended)
**Notes:** MIG-04 explicitly requires this pattern. Tests already use TESTING flag for coordinator startup.

---

## Claude's Discretion

- Alembic directory structure (alembic/ vs migrations/)
- Shell script entrypoint vs inline Docker CMD
- Exact revision message wording
- _seed_defaults() adjustment details

## Deferred Ideas

None
