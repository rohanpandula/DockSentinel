# DockSentinel UI redesign — what changed

Design brief (IA, nav model, per-journey flows): [../ui-redesign-brief.md](../ui-redesign-brief.md).
Screenshots: `shots/` (desktop 1440px, mobile 375px).

## IA before → after

| Before | After |
|---|---|
| Monitor: Overview · Events · Issues · Reports | **Monitor**: Now · Events · Issues · Reports |
| Configure: Settings · Exclusions · Prompts | **Tune**: Settings · Exclusions · Prompts |
| — | **Drill-down**: `/containers/<name>` (one new route) |
| Sidebar only | Sidebar + status pill on every page; bottom tab bar on phones |

Everything a container name appears on now links to the container drill-down.

## Journey → screen

1. **Is everything OK?** `/dashboard` opens on a colour-coded *verdict strip* ("All quiet" /
   "4 things need attention" / "Sentinel is degraded"), then **Needs attention** (today's
   critical/warning verdicts that did *not* reach the phone, each with the reason),
   **Fleet today** (one tile per container, worst-first), then numbers and recent events.
   Rows newer than your last visit are marked `new` (localStorage, per browser).
2. **Something alerted on my phone.** Telegram footer now links
   `/insights?container=X&event=<id>`; that renders an **event spotlight**: verdict, what
   happened, alert outcome + why, root cause, fix, log excerpt, container history strip,
   and actions — Mute 24h / Unmute, Open issue, **Analyze again**, Container.
3. **Why did I NOT get alerted?** `/containers/<name>` shows a **pipeline funnel**
   (chunks seen → keyword → dedup → rate limit → coalesce → cooldown → LLM → alert-worthy
   → alerted) with the drop count, the plain-English reason and a link to the exact knob;
   a suppression histogram; the knobs in effect; the container timeline; issues.
4. **First run.** A three-step **guided stepper** replaces the checklist: LLM (transport,
   model, base URL, key + inline *Save & test*), Telegram (BotFather how-to, save token,
   **Detect chat id** via `GET /api/telegram/detect-chat`, send test), Start. Re-openable
   from Settings → *Re-run setup* (`/dashboard?setup=1`).
5. **Weekly review.** Reports gains a *Last 7 days* strip (alerts, verdicts, held-back,
   open issues, noisiest containers) with jumps to triage/tuning; Settings gains a
   *last 7 days at a glance* card **and a badge on every noise knob** saying what that knob
   actually did ("12 skipped", "1 held", "3 inherited"), plus a mutes/exclusions summary.
6. **Model tinkering.** Issue detail keeps a **run history per issue** (localStorage):
   every Try-another-LLM call is recorded with model, prompt, latency; pin two to compare
   answers **side by side**; "again" re-runs the same prompt on that model. Prompt studio
   gains Edit / Built-in default / Side-by-side tabs, dirty state, char+line counts and
   "copy default into editor".

## Files changed

**New**
- `app/web/pipeline_view.py` — status/suppression explanations, funnel builder, tuning impact
- `app/templates/container.html` — journey 3 drill-down
- `app/templates/_macros.html` — severity badge, container link, outcome badge, event row
- `tests/test_ui_journeys.py` — 21 tests across the six journeys
- `docs/ui-redesign-brief.md`, `docs/ui-redesign/` (this file + screenshots)

**Changed**
- `app/web/routes.py` — `/containers/<name>`; `?event=` spotlight and `?outcome=` filter on
  `/insights`; fleet/attention/setup rollups on the dashboard; tuning stats on `/settings`;
  weekly stats on `/reports`; `next=` support on analyze/toggle
- `app/api/telegram.py` — `GET /api/telegram/detect-chat`
- `app/services/telegram_bot.py` — remembers the last chat that messaged the bot
- `app/services/alerts.py` — alert footer deep-links `&event=<id>`
- `app/templates/*.html`, `app/static/css/app.css`, `app/static/app.js` — redesign
- `tests/test_mutes.py` — updated with the deep-linked alert footer

## API contract

No endpoint removed or renamed; request/response shapes unchanged. Additions only:
one web route (`/containers/<name>`), one JSON endpoint (`/api/telegram/detect-chat`),
and two optional query params on `/insights` (`event`, `outcome`).

## Tests

`python -m pytest -q` → **185 passed** (164 pre-existing + 21 new), coverage 87.7%.
