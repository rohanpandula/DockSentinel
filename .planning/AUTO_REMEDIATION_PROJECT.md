# DockSentinel Auto-Remediation — Project Brief

## What

Closed-loop container remediation with human-in-the-loop approval via Telegram. When DockSentinel detects a critical issue, it generates an executable fix plan, presents it for approval, and executes it on confirmation.

## User Story

As an operator receiving a critical alert in Telegram, I want DockSentinel to:
1. **Auto-generate a fix plan** — concrete commands (docker exec, restart, config changes) the LLM produces from the event context
2. **Present the plan** — Telegram message with what it'll do, which container it'll touch, what commands it'll run, and the expected outcome
3. **Wait for my approval** — inline keyboard [Approve Fix] [Reject Fix] [Edit Plan]
4. **Execute on approval** — run the commands via Docker SDK, capture stdout/stderr
5. **Report back** — success/failure with output, update the local issue

## Architecture

### New LLM call: Remediation Planner

After the existing triage call (which produces summary + root_cause + fix_suggestion as free text), a **second structured LLM call** generates an executable plan:

```json
{
  "steps": [
    {
      "description": "Create the missing logs directory",
      "type": "docker_exec",
      "container": "unraid-mcp",
      "command": ["mkdir", "-p", "/app/logs"],
      "rollback": null
    },
    {
      "description": "Restart the container to pick up the new directory",
      "type": "container_restart",
      "container": "unraid-mcp",
      "rollback": null
    }
  ],
  "expected_outcome": "unraid-mcp starts successfully and writes logs to /app/logs/unraid-mcp.log",
  "risk_level": "low",
  "estimated_downtime_seconds": 15
}
```

### Execution Engine

New service `app/services/remediation.py`:
- `RemediationEngine` takes a plan (list of steps) and executes via Docker SDK
- Supported step types:
  - `docker_exec` — run command inside a container
  - `container_restart` — docker restart
  - `container_stop` / `container_start`
  - `env_update` — modify env var (requires recreate — flag to user)
  - `host_exec` — **BLOCKED by default** — requires explicit opt-in setting
- Each step: execute, capture output, check exit code
- On failure: stop, report which step failed, offer rollback if available
- Full audit log in LocalIssue.discussion

### Telegram Flow

```
[Existing alert with Reject/Approve/Discuss]
          ↓ (user taps Approve)
[Issue created]
          ↓ (auto-trigger remediation planner)
New Telegram message:
  "🔧 FIX PLAN for unraid-mcp (#3)
   
   Step 1: Create /app/logs directory
     docker exec unraid-mcp mkdir -p /app/logs
   
   Step 2: Restart container
     docker restart unraid-mcp
   
   Risk: low | Downtime: ~15s
   
   [✓ Run Fix] [✕ Skip] [✏ Edit]"
          ↓ (user taps Run Fix)
Execute steps sequentially
          ↓
"✅ FIX APPLIED
  Step 1: mkdir -p /app/logs → exit 0
  Step 2: docker restart → container healthy after 8s
  
  Verify: container logs show successful startup"
```

### Security Guardrails

| Guardrail | Behavior |
|---|---|
| Command whitelist | Only allowed command prefixes: `mkdir`, `chmod`, `chown`, `cp`, `mv`, `rm` (files only), `cat`, `sed`, common package managers. No `curl | bash`, no `eval`, no shell pipes by default |
| Container scope | Can only exec into the AFFECTED container (the one that triggered the alert) unless explicitly overridden |
| No host commands | `host_exec` type requires `REMEDIATION_HOST_EXEC=true` env var — off by default |
| Dry-run mode | `REMEDIATION_DRY_RUN=true` — plans are generated and presented but [Run Fix] is replaced with [Dry Run] that only shows what WOULD happen |
| Audit trail | Every executed command, its output, and exit code logged to LocalIssue.discussion + a dedicated `remediation_log` table |
| Timeout | 30s per step, 120s total per plan. Configurable |
| Rollback | If step N fails, offer to run rollback commands for steps 1..N-1 |

### Settings

| Setting | Default | Purpose |
|---|---|---|
| `auto_remediation_enabled` | `false` | Master switch — when off, fix plans are generated but not executable |
| `remediation_auto_plan` | `false` | Auto-generate plan on issue approval (vs manual trigger) |
| `remediation_dry_run` | `true` | Present plans but don't actually execute |
| `remediation_host_exec` | `false` | Allow commands on the Docker host (dangerous) |
| `remediation_timeout_seconds` | `30` | Per-step timeout |
| `remediation_allowed_containers` | `*` | Glob pattern for which containers can be remediated |

### Data Model

New table `remediation_plans`:
- id, issue_id (FK), steps (JSON), status (planned/approved/executing/completed/failed/rolled_back), risk_level, expected_outcome, execution_log (JSON array of step results), telegram_message_id, created_at, executed_at, completed_at

### Phases

**Phase 1: Remediation Planner (LLM → structured plan)**
- New prompt template `REMEDIATION_PLANNER` that takes the triage output and produces the structured JSON plan
- New endpoint `POST /api/issues/<id>/generate-plan` 
- Plan stored in `remediation_plans` table
- Telegram delivery of the plan with approve/skip buttons
- UI: plan viewer on issue detail page

**Phase 2: Execution Engine**
- `RemediationEngine` service with Docker SDK exec
- Step-by-step execution with output capture
- Telegram callback handler for [Run Fix]
- Post-execution verification (check container health after fix)
- Audit logging

**Phase 3: Guardrails + Polish**
- Command whitelist validation
- Dry-run mode
- Settings UI for remediation config
- Rollback support
- Rate limiting (max N fixes per hour)

## Prior Art in This Codebase

- `app/services/sentinel.py` — the existing triage pipeline this hooks into
- `app/services/telegram_bot.py` — the callback handler this extends
- `app/models/local_issue.py` — the issue model this attaches plans to
- `app/services/chunk_coalescer.py` — pattern for structured background work
- Docker SDK already available (`docker.from_env()` used in sentinel + routes)

## Out of Scope (for now)

- Multi-container orchestrated fixes (e.g. "restart A then B then C in order")
- Terraform/IaC-level changes
- Network topology changes
- Persistent config file edits (compose file rewrites)
- Scheduled/recurring remediation

## Success Criteria

- [ ] LLM generates structured, parseable fix plans from triage output
- [ ] Plans are presented in Telegram with inline approval keyboard
- [ ] Approved plans execute via Docker SDK with captured output
- [ ] Failed steps halt execution and report clearly
- [ ] Full audit trail in the local issue + remediation_plans table
- [ ] Dry-run mode works end-to-end (plan + present, no execute)
- [ ] Security guardrails prevent dangerous commands
- [ ] Settings page has remediation controls
- [ ] The unraid-mcp permission-denied issue could be fixed through this system
