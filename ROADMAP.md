# DockSentinel Roadmap

> Living document tracking planned features, organized into phases.
> Current state: **MVP complete** with dual LLM transport (API + CLI), call reduction optimizations, and Flask/Jinja2 dashboard.

---

## Phase 1 — Modern Frontend (React SPA)

Replace the Flask/Jinja2 templates with a React single-page application. This comes first so every subsequent feature is built on the new UI from the start.

### 1.1 Project Scaffold
- [ ] Create `frontend/` directory with Vite + React + TypeScript
- [ ] Set up Tailwind CSS (migrate from CDN to proper build)
- [ ] Configure API proxy (Vite dev server → Flask backend on `:5000`)
- [ ] Add ESLint, Prettier, and basic CI lint check

### 1.2 Core Layout & Navigation
- [ ] App shell with sidebar navigation (collapsible)
- [ ] Dark/light mode toggle with system preference detection
- [ ] Responsive design (mobile-friendly sidebar → hamburger menu)
- [ ] Toast notification system for async feedback
- [ ] Loading skeletons for all data-fetching states

### 1.3 Dashboard Page
- [ ] Real-time event feed with WebSocket push (Flask-SocketIO or SSE)
- [ ] Event severity breakdown chart (critical/warning/noise over time)
- [ ] Active containers list with live status indicators
- [ ] Sparkline graphs for events-per-hour per container
- [ ] Latest nightly report summary card
- [ ] Quick-action buttons: toggle sentinel, analyze now, generate report

### 1.4 Insights / Events Page
- [ ] Searchable, filterable, paginated event table
- [ ] Filter by: container, status, classification, date range, keyword
- [ ] Event detail modal with full log excerpt, LLM analysis, and fix suggestion
- [ ] Bulk actions: mark as resolved, export to CSV
- [ ] Timeline visualization for correlated events across containers

### 1.5 Settings Page
- [ ] Organized settings into collapsible sections (LLM, Alerts, Call Reduction, CLI)
- [ ] Inline validation with real-time feedback
- [ ] Test LLM / Test Telegram buttons with inline result display
- [ ] Settings import/export (JSON backup/restore)

### 1.6 Other Pages
- [ ] Reports page with markdown rendering and diff view between reports
- [ ] Prompt Studio with syntax highlighting, version history, and diff
- [ ] Exclusions page with pattern testing (preview which containers match)

### 1.7 Backend Adjustments
- [ ] Add WebSocket/SSE endpoint for real-time event streaming
- [ ] Add pagination parameters to all list endpoints (`offset`, `limit`, `sort`)
- [ ] Add `GET /api/stats` endpoint for dashboard aggregation queries
- [ ] CORS configuration for development (Vite dev server)
- [ ] Serve React build output from Flask in production (single container)

---

## Phase 2 — Actionable Fix Suggestions

Make the LLM's fix suggestions more useful and visible. Suggestions are shown in the UI and alerts — the operator decides whether to act.

### 2.1 Enhanced LLM Analysis
- [ ] Expand sentinel prompt to request structured fix suggestions:
  - `fix_type`: restart, config_change, resource, investigate, ignore
  - `fix_command`: suggested shell command (if applicable)
  - `fix_urgency`: immediate, next_maintenance, informational
  - `related_docs_hint`: search terms for documentation lookup
- [ ] Add confidence threshold setting — only show suggestions above N%
- [ ] Add per-container prompt overrides (custom system prompts per container type)

### 2.2 Fix Suggestion UI
- [ ] Dedicated "Suggested Fixes" panel on the dashboard
- [ ] Fix suggestion cards with: severity badge, container name, summary, suggested command
- [ ] "Copy command" button for suggested shell commands
- [ ] "Mark as resolved" / "Dismiss" / "Snooze" actions per suggestion
- [ ] Fix suggestion history with outcome tracking (did the fix work?)

### 2.3 Fix Knowledge Base
- [ ] Store successful fix patterns in SQLite (container type + error pattern → fix)
- [ ] When a new error matches a previously resolved pattern, surface the past fix
- [ ] Allow operators to annotate fixes with notes ("this worked" / "didn't help")
- [ ] Export/import fix patterns for sharing between DockSentinel instances

---

## Phase 3 — SMTP Email Alerts (Full Notification Center)

Configurable email notification system with per-severity rules, multiple recipients, and digest scheduling.

### 3.1 SMTP Backend
- [ ] Add SMTP settings to Settings model: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password`, `smtp_from`, `smtp_use_tls`
- [ ] Email sending service with connection pooling and retry logic
- [ ] HTML email templates (responsive, dark-mode friendly)
- [ ] "Test Email" button in settings
- [ ] Rate limiting per recipient to prevent email storms

### 3.2 Notification Rules Engine
- [ ] `notification_rules` table: severity filter, container filter, recipient(s), channel (email/telegram/both), schedule
- [ ] Rule builder UI: "When [severity] from [container pattern] → send to [recipients] via [channel]"
- [ ] Support multiple recipients per rule (comma-separated or recipient groups)
- [ ] Quiet hours / maintenance windows (suppress non-critical alerts during specified times)
- [ ] Escalation rules: if critical alert not acknowledged within N minutes, escalate to different recipient

### 3.3 Digest Emails
- [ ] Configurable digest frequency: daily, twice-daily, weekly
- [ ] Digest content: event summary, top containers by activity, open fix suggestions, nightly report link
- [ ] Per-recipient digest preferences (some want daily, some want weekly)
- [ ] Unsubscribe link / manage preferences link in every email

### 3.4 Notification History
- [ ] `notification_log` table: timestamp, channel, recipient, event_id, status, error
- [ ] Notification history page in UI with delivery status tracking
- [ ] Retry failed notifications with exponential backoff

---

## Phase 4 — RAG (Retrieval-Augmented Generation)

Give the LLM access to contextual knowledge so it produces better analysis and more relevant fix suggestions.

### 4.1 Vector Store Setup
- [ ] Add ChromaDB (or SQLite-VSS) as embedded vector database
- [ ] Document chunking pipeline: split docs into overlapping chunks, compute embeddings
- [ ] Embedding model: use a local model (sentence-transformers) or the configured LLM's embedding endpoint
- [ ] Background indexing job (don't block the main event loop)

### 4.2 Knowledge Sources

#### Past Incidents (automatic)
- [ ] After each `analyzed` event, index the log excerpt + LLM analysis + fix suggestion
- [ ] After operator marks a fix as "resolved", boost that entry's relevance
- [ ] Decay old incidents over time (configurable retention window)
- [ ] Dedup similar incidents in the index to avoid noise

#### Container Documentation (semi-automatic)
- [ ] Fetch and index official docs for detected container images:
  - Radarr/Sonarr wiki, Home Assistant docs, Plex support, Jellyfin docs, Traefik docs, etc.
- [ ] Container image detection: parse `docker inspect` image names → map to doc URLs
- [ ] Scheduled re-index (weekly) to pick up doc updates
- [ ] Admin UI to add/remove doc sources and trigger manual re-index

#### Custom Runbooks (manual)
- [ ] Upload page for custom markdown/text runbooks
- [ ] Runbook editor in the UI with live preview
- [ ] Tag runbooks with container patterns so they're retrieved for relevant errors
- [ ] Example runbooks: "How to recover Radarr DB corruption", "Plex transcoder troubleshooting"

### 4.3 RAG-Enhanced Analysis Pipeline
- [ ] Before calling the LLM for log analysis, query the vector store for relevant context
- [ ] Inject top-K relevant chunks into the system prompt (with source attribution)
- [ ] Token budget management: RAG context competes with log content for the input window
- [ ] Setting: `rag_enabled` (bool), `rag_top_k` (int, default 3), `rag_max_tokens` (int, default 2000)
- [ ] Display RAG sources in the event detail view ("Based on: [doc name], [past incident #123]")

### 4.4 RAG for Nightly Reports
- [ ] Include trending patterns from the knowledge base in nightly report context
- [ ] Reference past similar incidents when summarizing recurring issues
- [ ] Suggest runbook links for open issues

---

## Phase 5 — Advanced Features

### 5.1 Multi-Channel Alerts
- [ ] Slack webhook integration
- [ ] Discord webhook integration
- [ ] Webhook (generic) — POST event JSON to any URL
- [ ] PagerDuty / Opsgenie integration for on-call escalation

### 5.2 Anomaly Detection
- [ ] Baseline log volume per container (rolling 7-day average)
- [ ] Alert on sudden volume spikes (3x baseline in 15-minute window)
- [ ] Container restart frequency tracking with anomaly detection
- [ ] Resource correlation: if container logs errors AND restarts, escalate severity

### 5.3 Multi-Host Support
- [ ] Connect to multiple Docker daemons (multiple `DOCKER_HOST` entries)
- [ ] Per-host grouping in the UI
- [ ] Cross-host correlation (same error across multiple hosts)

### 5.4 User Authentication
- [ ] Basic auth with bcrypt password hashing
- [ ] Session management with configurable timeout
- [ ] Optional SSO via OAuth2 (Google, GitHub)
- [ ] Role-based access: admin (full control) vs viewer (read-only dashboard)

### 5.5 API v2
- [ ] OpenAPI/Swagger spec with auto-generated docs
- [ ] API key authentication for external integrations
- [ ] Webhook subscriptions: register external URLs to receive events in real-time
- [ ] Bulk operations: analyze multiple containers, batch update settings

### 5.6 Performance & Scale
- [ ] Optional PostgreSQL backend (for larger deployments)
- [ ] Event retention policies (auto-prune events older than N days)
- [ ] Background worker process (separate from web server) for LLM calls
- [ ] Prometheus metrics endpoint (`/metrics`) for monitoring DockSentinel itself

---

## Version Targets

| Version | Phase | Key Deliverable |
|---------|-------|-----------------|
| **v0.1** | ✅ Done | MVP: Flask dashboard, dual LLM transport, CLI backends |
| **v0.2** | ✅ Done | Call reduction: prefilter, dedup, rate limiting, keyword batching |
| **v1.0** | Phase 1 | React SPA with real-time WebSocket updates |
| **v1.1** | Phase 2 | Actionable fix suggestions with knowledge base |
| **v1.2** | Phase 3 | Full notification center (SMTP + rules engine + digests) |
| **v2.0** | Phase 4 | RAG-enhanced analysis with docs, history, and runbooks |
| **v2.x** | Phase 5 | Multi-channel alerts, anomaly detection, auth, multi-host |
