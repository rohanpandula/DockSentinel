# DockSentinel — Adversarial Review (2026-08-15)

Static review of `a7f02ff`; tests run under Python 3.12 (Homebrew) — 46 passing at baseline. All findings below were verified by reading the actual code path end-to-end.

## Status of the top 5 — FIXED on branch `review-fixes` (60 tests pass; 46 → 60)

| # | Fix landed |
|---|---|
| 1 | `app/schemas/settings.py` masks `llm_api_key`/`telegram_token` as `********`; PUT/form treat blank/masked as "keep". Settings page no longer renders secrets. New `app/security.py`: optional HTTP basic auth via `BASIC_AUTH_USER`/`BASIC_AUTH_PASSWORD` (health stays open). |
| 2 | `app/security.py` rejects state-changing requests with a foreign `Origin`/`Referer` (403). Web settings form now uses the same allowlist + pydantic validation as the API (400 + error banner on bad input; `id`/`updated_at` untouchable). `/exclusions/delete/<id>` is POST-only. |
| 3 | `try-llm`: an overridden `base_url` never receives the stored key (only an api_key sent in the same request); non-http(s) URLs → 400. `ollama/models`: http(s) only, generic error text (no probing oracle). |
| 4 | `docker_watcher._tail_container`: reconnect loop with backoff on stream drop (docker-py read timeout), pops itself from `_workers` on exit and pokes reconcile; line-callback exceptions are logged and skipped instead of killing the stream; event-thread death now logs. |
| 5 | `docker-entrypoint.sh` stamps `0001` or `0002` (detected from the actual `settings` columns) instead of `head`, so 0003–0005 apply on upgrade. |
| — | Bonus: `keyword_flush_delay_lines` schema type `str`→`int`; range bounds on numeric settings (`nightly_hour` 0–23 etc.). Tests: `tests/test_security.py` (11), `tests/test_docker_watcher.py` (3). |

## Batch 2 — FIXED (items 6, 7, 8, 10, 14; 76 tests pass, coverage 81% → gate green)

| # | Fix landed |
|---|---|
| 6 | `verdict_parser.extract_json_object`: strips ``` fences, extracts first balanced `{…}` (string/escape-aware). Parse errors now call `_record_llm_failure` → runtime `degraded`, `llm_failure_count` increments. |
| 7 | `cli_backends.build_backend_env`: allowlisted env only (PATH/HOME/locale/proxy + provider prefixes; extra via `DOCKSENTINEL_CLI_ENV_PASSTHROUGH`) — `SECRET_KEY`, `DATABASE_URL`, `TELEGRAM_*`, `BASIC_AUTH_*`, `DOCKER_HOST` never reach the CLI. Logs wrapped in `<logs>` with an untrusted-data instruction; Telegram fix labelled "model-generated — verify before running". Wrappers `exec` the real CLI; `claude.sh` adds `--tools ""` when supported. |
| 8 | `TelegramBotService._dispatch` drops any update whose chat id ≠ `settings.telegram_chat_id` (and everything when unset); `get_by_telegram_message` is chat-scoped. |
| 10 | `TelegramNotifier.get_updates` raises on HTTP error → poll loop backs off 5s instead of hot-looping. |
| 14 | CLI backend runs in its own process group (`start_new_session=True`) and is `SIGKILL`ed as a group on timeout — no orphaned `claude`/`gemini`/`codex` still burning tokens. |

### Second-opinion pass (local Qwen3-27B, adversarial prompt)
Batch 1 diff reviewed. Of 8 claims: **3 acted on** — reverse-proxy `Host` rewrite would 403 legit browser POSTs (now honours `X-Forwarded-Host`); no way to clear a secret (JSON `null` now clears); reconcile poked on clean container stop (now only on error path). **5 rejected after checking code:** `_reconcile_now` "may be undefined" (it's in `__init__`); httpx "follows redirects by default" (it doesn't — `follow_redirects=False` is httpx's default); `VAR=$(cmd)` "escapes `set -e`" (POSIX: exit status of assignment-only command is that of the last command substitution, so `set -e` fires); error handlers "registered after security so 403 is unformatted" (registration order is irrelevant to handler lookup); "settings race condition" (none identified — the point restated the intended keep-on-blank behaviour). Batch 2 diff (third attempt succeeded): reviewer walked the JSON extractor through 7 edge cases and found no defect; chat-id comparison judged correct; **2 minor points acted on** (log + fallback `proc.kill()` if `killpg` hits `PermissionError`; truncate parse-error text stored in `last_error`; also pass `PYTHONPATH`/`PYTHONUNBUFFERED`/`VIRTUAL_ENV` to CLIs). **Rejected:** "a non-`exec` wrapper's child survives the timeout" — wrong, `start_new_session` + `killpg` kills the whole group (covered by `test_cli_backend_timeout_kills_child_process_group`, which uses exactly that shape); "poll loop may not catch RuntimeError" — it does (`telegram_bot.py` `_loop` wraps in `except Exception` + 5s backoff).

## Do first (5 items) — original findings

| # | Sev | Finding | Where | Fix |
|---|---|---|---|---|
| 1 | CRIT | **Secrets served in plaintext, no auth.** `GET /api/settings` returns `llm_api_key` + `telegram_token`; settings page renders them into `value=`. Anyone who can reach the port owns the LLM key and the Telegram bot. | `app/api/settings.py:40-44`, `app/schemas/settings.py:12,19`, `app/templates/settings.html:35,107` | Mask secrets in read schema (write-only, "leave blank to keep"); add basic-auth/token middleware. |
| 2 | CRIT | **CSRF + mass-assignment on the settings form.** Plain form POST, no token, `hasattr`/`setattr` on any `Settings` column (`llm_base_url`, `telegram_chat_id`, even `id`). A malicious web page the operator visits can redirect all logs + `Bearer <key>` to attacker, or redirect alerts. `GET /exclusions/delete/<id>` deletes via `<img src>`. | `app/web/routes.py:60-91,111` | Flask-WTF CSRF (or SameSite=Strict + Origin check); explicit allowlist + `UpdateSettingsBody` validation; delete → POST. |
| 3 | HIGH | **SSRF + stored-key exfil.** `POST /api/issues/<id>/try-llm` accepts `base_url` override but keeps stored `api_key` → server sends your key + issue body (logs) to attacker URL. `GET /api/ollama/models?base_url=` fetches any URL. | `app/api/issues.py:23-63,104-107` | Only honour `base_url` when `api_key` also given; block private ranges; or drop overrides and use stored settings. |
| 4 | HIGH | **Tail thread dies silently, never re-attached.** `_tail_container` `except Exception: return` leaves the id in `_workers`, so `reconcile()` thinks it's attached. docker-py's default 60s read timeout on `logs(follow=True)` for a quiet container, or any DB error in `handle_log_line`, kills monitoring for that container until it restarts — with no log line. | `app/services/docker_watcher.py:162-177,97-117` | In `finally`, pop from `_workers` under lock + `logger.exception`; wrap `line_callback` in try/except; reconnect loop / `timeout=None`. |
| 5 | HIGH | **Legacy DB migration skip.** Entrypoint runs `alembic stamp head` for v0.2 DBs → migrations 0003–0005 never apply (`chunk_coalesce_window_seconds`, `local_issues`, `llm_model`) → `no such column` on boot, and the condition never re-fires. | `docker-entrypoint.sh:20-27` | `alembic stamp <rev of 0002>` then `upgrade head`. |

## Do next (correctness)

| # | Sev | Finding | Where | Fix |
|---|---|---|---|---|
| 6 | HIGH | Verdict parser does raw `json.loads`; CLI backends (`claude -p`, `gemini`, `codex`) routinely wrap JSON in ``` fences → every verdict `parse_error`, no alert, runtime never marked degraded, still burns rate-limit budget. | `app/services/verdict_parser.py:34-47`, `sentinel.py:261-271` | Strip fences / extract first `{…}`; count parse errors toward `llm_failure_count`. |
| 7 | HIGH | Prompt injection from container logs → agentic CLI backends run with full `os.environ` (SECRET_KEY, provider keys) and can read `/data/docksentinel.db`. `fix_suggestion` is pushed verbatim to Telegram as "exact shell commands". | `app/services/cli_backends.py:59-68`, `llm-backends/*.sh`, `alerts.py:88-91` | Minimal env; non-agentic flags (`--allowedTools ""` / sandbox); wrap logs in an "untrusted data" delimiter; label alerts as model-generated. |
| 8 | MED | Telegram bot: no `chat_id` allowlist; `get_by_telegram_message` isn't chat-scoped. Stranger DMs bot, replies to msg #N in their chat → collides with an issue's `telegram_message_id`, gets log excerpts + LLM answers, burns your budget. | `app/services/telegram_bot.py:169-198`, `app/repositories/local_issues.py:18-24` | Drop updates where `chat.id != settings.telegram_chat_id` in `_dispatch`; add chat filter to lookup. |
| 9 | MED | `analyze_container_now` bypasses the exclusion list → unauthenticated log read of *any* host container; also leaks a `docker.from_env()` client per call. | `app/services/sentinel.py:296-315` | Enforce `is_excluded_container`; restrict to watched IDs; share client. |
| 10 | MED | Telegram polling hot-loops on persistent error (401/409/DNS) — `get_updates` swallows and returns `[]`, `_loop` re-polls with no sleep. | `app/services/telegram.py:93-111`, `telegram_bot.py:78-97` | Raise/return None on error → `_stop.wait(5)`. |
| 11 | MED | Alert dedupe keys on `chunk_hash`; timestamps/PIDs/`[coalesced batch…]` prefix make collisions impossible → crash-looping container alerts up to global limit (240/h). | `app/services/alerts.py:59-62` | Dedupe on `(container_id, classification)` or hash the LLM summary. |
| 12 | MED | `LogBuffer`: no timer flush (error + silence sits until next line when `keyword_flush_delay_lines>0`); `estimate_tokens("".join(lines))` per line = O(n²)/tiktoken per line; no lock though flushed from 3 threads; per-line pipeline does 3+ DB queries per log line from N threads on SQLite with no busy_timeout. | `app/services/log_buffer.py:105-148`, `sentinel.py:150-160` | Idle-flush tick in health thread; incremental token count; `threading.Lock`; cache settings/exclusions with TTL; set `connect_args={"timeout": 30}`. |
| 13 | MED | Watcher `stop()` never joins event/reconcile threads and `start()` clears the shared stop event → each restart leaks a reconcile thread. | `docker_watcher.py:34-55` | Join with timeout; per-generation stop event. |
| 14 | MED | CLI backend timeout kills only the bash wrapper; `claude`/`gemini`/`codex` children keep running (still spending tokens) and bypass the semaphore. | `cli_backends.py:61-73`, `llm-backends/*.sh` | `start_new_session=True` + `os.killpg` on timeout, or `exec` in wrappers. |
| 15 | MED | `analysis_events` never pruned — every 16k of noise / every excluded container every 5 min inserts a row forever. | `sentinel.py:187-192` | Daily prune job for `skipped/dedup_skipped/rate_limited` rows > N days. |

## Functionality review (does it deliver "cure log fatigue"?)

**Verdict:** the core loop (keyword hit → LLM verdict → Telegram card with Reject/Approve/Discuss → local issue) works and is more actionable than a raw log tail. But it only catches text-log errors containing one of 7 words; the biggest homelab signals (restarts/OOM kills, Python tracebacks, warnings) never reach the operator, and nothing the operator decides (reject/close/exclude) feeds back into suppression. Onboarding is ~9 manual steps with two wrong-for-Unraid defaults; several pages are read-only dead ends.

Top 8 gaps:
1. **Container die/restart/OOM never becomes an event.** `docker_watcher.py:79-83` uses `start/restart/die` only to attach/detach; a crash-looping container with exit 137 and no log line is invisible, though the briefing prompt asks for a "Container Restarts" section (`prompts.py:45-46`; `briefing.py:60-61` admits it's inferred). → Record a synthetic `container_died` event with exit code; alert on N restarts in M minutes.
2. **Default keyword list misses common errors.** `settings.py:34` = `error,exception,fatal,panic,critical,refused,timeout` with `\b` matching (`prefilter.py:21`) → `ValueError:`, `Traceback`, `failed`, `denied`, `killed`, `oom`, `unhealthy` don't match; `timeout=30` config echoes do. Multi-line traces cut after 5 trailing lines (`log_buffer.py:135-137`). → Add `traceback,failed,denied,killed,oom,warn`; continue chunk while next line is indented / starts with `at `.
3. **Warnings never leave the DB; no alert threshold.** `sentinel.py:285` alerts only on `critical`; nightly report is generated but never sent to Telegram (`coordinator.py:60-62`). → `alert_min_classification` setting; push briefing to chat.
4. **Decisions don't close the loop.** Reject/Approve/Close only flip `LocalIssue.status`; dedupe still keys on `chunk_hash` (`alerts.py:59-60`) so a rejected alert re-fires after cooldown. No mute/snooze/ignore-pattern from Telegram or issue page. → On Reject offer `[Mute container 24h] [Ignore this pattern]`; skip alerts for containers with an open/rejected issue on the same summary.
5. **Prompt lacks context and rubric.** `sentinel.py:243` sends only `Container: <name>` + logs; no image, restart count, uptime, prior alerts. `prompts.py:22-34` never defines noise/warning/critical, no JSON example, no `response_format` (`llm_client.py:77-82`) — llama3 will call any "error" line critical. → Add rubric + one-shot example; pass image/restart-count/last-3-events; request `json_object` where supported.
6. **Setup dead ends.** Default `llm_base_url=http://host.docker.internal:11434/v1` (`settings.py:11`) but compose files lack `extra_hosts: host-gateway` → fails on Linux/Unraid. Sentinel starts `enabled=False` with no prompt to start it. "Test LLM/Telegram" read *saved* settings (`api/settings.py:66-67`) so testing freshly typed values fails silently. Chat ID must be found by hand. → `extra_hosts`; save-then-test; chat-id discovery button; "Send test alert"; first-run "Sentinel is stopped" banner.
7. **Can't answer "why no alert?" / "what's up with container X".** "Noise" count lumps `skipped/dedup_skipped/rate_limited/queued`; Events page has no status filter and drops filter values on submit (`insights.html:16-33`); no per-container page; `alert_error` ("suppressed by cooldown") never displayed. → Status filter + sticky values; container detail page with mute toggle; show `alert_error` on rows.
8. **Reports page and alert card half-rendered.** `reports.html:48` dumps raw markdown; badge checks `ok/success` but statuses are `generated/llm_error` (`briefing.py:98,112`) so LLM-failed reports look fine; briefing feeds every event incl. `skipped` rows (`briefing.py:73-82`), omits open issues. Telegram card has no log excerpt or dashboard link. → Render markdown; feed analyzed events + open issues; add 5-line excerpt + link.

vs. Dozzle / Loki+Grafana / Uptime Kuma: no live per-container log view, no retention/search (1200-char excerpts only), no up/down status — users still need those tools alongside; the LLM triage card is the real niche but thin without restart tracking.

Does well: phone-friendly `[Reject][Approve][Discuss]` card with in-chat LLM thread; layered call-reduction (prefilter, dedup, per-container rate limit, coalescing) fully surfaced in Settings; Prompt Studio with versioning + "Try another LLM" on issues.

## API / UI / tests / ops (lower severity)

- `app/schemas/settings.py:69` — `keyword_flush_delay_lines: str | None` should be `int | None`; API 400s on integers. No range validation on any settings field (`nightly_hour` 0–23 etc.).
- `app/schemas/health.py:9` — `status` hard-coded `"ok"`; README says it reports `degraded`; Docker HEALTHCHECK can never fail on runtime errors. Derive from `SentinelState.runtime_status`.
- `docker-entrypoint.sh:31` — Werkzeug dev server in prod. Add `gunicorn -w 1 --threads 8` (must stay 1 worker: coordinator flock is per-process).
- README drift: `GET /api/events` doesn't exist; `try-llm` and `ollama/models` undocumented; `MDNS_PORT` default 5000 vs code `"80"`. `.env.example` missing `DOCKER_HOST`, `CLI_BACKENDS_DIR`, `APP_PORT`, `MDNS_*`.
- Tests: zero coverage on `api/issues.py`, `telegram_bot.py` (headline feature), `alerts.py`, `verdict_parser.py`, `chunk_coalescer.py`; `.coveragerc` omits `log_buffer.py`/`routes.py`/`config.py` so the 80% gate is measured on a shrunken denominator; `test_ui_routes.py:30` accepts `{200,302}` for every route; `test_api.py:30-80` asserts only status codes.
- No CI workflow; `npm install -g …@latest` and untagged base image → non-reproducible builds.
- UI: `routes.py:245-254` swallows analyze errors and redirects (no feedback); `app.js:7` `response.json()` on HTML 500 pages surfaces `SyntaxError` to user.

## Clean (checked, no issue)
No SQLi (ORM + `Literal` sort), no XSS (`textContent`, no `|safe`/`innerHTML`), no path traversal in backend name (`^[A-Za-z0-9_-]+$`), no secrets committed, migrations 0001–0005 match models, naive-UTC datetimes consistent, scheduler single-start protected by flock, HTTP LLM path has retry+timeout, non-root Docker user + HEALTHCHECK present.
