# DockSentinel UI redesign — design brief

Driven by six operator journeys, not by restyling pages. Server-rendered Flask/Jinja,
vanilla JS, one CSS file, no build step, no CDN.

## Current IA (before)

```
Monitor:   Overview · Events · Issues · Reports
Configure: Settings · Exclusions · Prompts
```
Problems against the journeys:
- Overview answers "is the sentinel process running", not "is my fleet OK". No per-container
  view; no "what changed since I last looked".
- Telegram alert links `/insights?container=X` → a filtered list; the operator has to find
  the row and expand it. No focused event view, no container history, no "analyze again".
- "Why did I NOT get alerted?" is unanswerable: pipeline outcomes are 9 opaque status
  strings scattered across rows; suppression reasons are hidden in a disclosure.
- Setup is a 3-item checklist card linking to a 60-field settings form.
- Noise knobs (13 numbers) give no feedback about what they did.
- "Try another LLM" is single-shot; you can't compare two verdicts.

## New IA (after)

```
Monitor:  Now (/dashboard) · Events (/insights) · Issues (/issues) · Reports (/reports)
Tune:     Settings (/settings) · Exclusions (/exclusions) · Prompts (/prompts)
Drill:    Container (/containers/<name>)   ← the ONE new web route
```
Nav model:
- Desktop: left sidebar, two groups (Monitor / Tune) + a persistent status pill
  (running/degraded/stopped) so J1 is answered from any page.
- Phone (≤900px): sticky topbar (title + hamburger drawer, kept for UI-50) **plus a bottom
  tab bar** Now · Events · Issues · Reports · More. Thumb-reachable, one tap from a Telegram
  deep-link landing to anywhere.
- Every container name anywhere in the app is a link to `/containers/<name>`.

## Per-journey screen flow

### J1 — "Is everything OK right now?" (Now page, <3 s)
1. **Verdict strip** at the very top: one sentence — "All quiet", "3 need attention",
   "Sentinel stopped", "LLM degraded" — colour-coded, with the 1–3 reasons inline.
2. **Needs attention** list: today's critical/warning events that were NOT alerted (and why),
   open issues count, degraded/LLM failures. Empty → a single green "nothing pending" line.
3. **Since you last looked**: JS stores last-visit timestamp in localStorage; rows newer than
   that get a "new" marker and a "N new since HH:MM" pill on the Now page.
4. **Fleet**: one tile per container seen today (worst verdict, event count, muted/excluded
   flags), sorted worst-first, each linking to the container drill-down.
5. Today's numbers, recent events, latest report, analyze-now, mutes — below the fold.

### J2 — Telegram alert → dashboard
Alert footer now links `/insights?container=X&event=ID` (existing substring preserved).
`/insights?event=ID` renders an **Event spotlight** above the list: verdict, summary, root
cause, fix, log excerpt, alert outcome + reason, model/latency/confidence, container
history strip (last 8 events for that container), and actions: Mute 24h/Unmute,
Open/Create issue link, Analyze again (POST /sentinel/analyze), Container drill-down.

### J3 — "Why did I NOT get alerted?" (Container drill-down)
`/containers/<name>`:
1. Header: attached? muted? excluded (matching rule)? last verdict.
2. **Pipeline funnel (24 h)**: chunks seen → passed prefilter → not deduped → not rate-limited
   → not queued/cooldown → analyzed → alert-worthy → alerted. Each stage shows the drop count
   and the knob that caused it (linked to Settings).
3. **Suppression reasons**: histogram of `alert_error` values (mute / cooldown / confidence /
   rejected-issue / global rate limit).
4. Timeline of the container's events with a plain-English "why" per status.
5. Actions: analyze now, mute/unmute, exclude, open issues for this container.

### J4 — First-run setup
Dashboard shows a **guided stepper** (not a checklist card) until LLM tested, Telegram
connected and sentinel started: Step 1 LLM (transport/base URL/model/key + Test LLM inline),
Step 2 Telegram (token, chat id, **Detect chat id** — bot records the last unauthorised chat
that messaged it, + Test), Step 3 Start sentinel. Each step saves via `PUT /api/settings`,
shows inline result, and advances. `?setup=1` re-opens it any time (link in Settings).

### J5 — Weekly review
- Reports page: reading pane + "this week" summary strip (issues opened/closed, alerts,
  noisiest containers) + jump to open issues.
- Settings → **Noise & alerts** section shows, next to each knob, what it did in the last
  7 days ("dedup window skipped 412 chunks", "confidence gate held back 3 alerts", …).
- Mutes and exclusions listed in the same tuning context.

### J6 — Model tinkering
- Issues detail: "Try another LLM" → **Compare verdicts**: every run is appended to a
  per-issue comparison table (model, transport, latency, answer), persisted in localStorage;
  two answers can be pinned side-by-side; one-click "run same prompt on another model".
- Prompts: editor + read-only default alongside, diff indicator, char/line counts, and
  "test on an issue" link.

## Contracts preserved
- All existing routes/endpoints and form field names.
- Test-greppable strings: "Sentinel is stopped", "Skipped (prefilter)", "Noise (LLM)",
  "Muted containers", "No containers are muted", "Mute container 24h", "muted until",
  "Unmute web", ">Unmute<", `class="badge badge--ok">generated`, "LLM call failed",
  `value="llm_error" selected`, `disclosure__summary`, "issue #", "/issues?id=",
  `Dashboard: /insights?container=…`, `Event ID: …`, checklist semantics of setup state.
