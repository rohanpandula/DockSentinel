"""Read-only view helpers that turn raw AnalysisEvent rows into the plain-English
pipeline story the UI tells: why a chunk stopped where it did, which knob did it,
and how a container's chunks funnel down to alerts.

Pure functions over already-loaded rows — no queries here."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from app.models import AnalysisEvent, Settings
from app.services.sentinel import classification_rank

# status -> (short label, plain-English reason, settings anchor or None, knob label)
STATUS_EXPLAIN: dict[str, tuple[str, str, str | None, str | None]] = {
    "analyzed": ("analyzed", "Sent to the LLM and classified.", None, None),
    "skipped": ("skipped · prefilter", "No keyword from the keyword list matched, so the chunk never reached the LLM.", "budgets", "Keyword list"),
    "dedup_skipped": ("skipped · duplicate", "Identical chunk was already analysed inside the dedup window.", "limits", "Dedup window"),
    "analysis_cooldown": ("skipped · cooldown", "Looks like the previous verdict for this container; the verdict was inherited instead of re-asking the LLM.", "alerts", "Analysis cooldown"),
    "rate_limited": ("skipped · rate limit", "This container already used its LLM-call budget for the window.", "limits", "Container rate limit"),
    "queued": ("queued · coalescing", "Held to be merged with neighbouring chunks before one LLM call.", "limits", "Coalesce window"),
    "parse_error": ("error · parse", "The LLM answered but the reply was not valid verdict JSON.", "llm", "LLM"),
    "llm_error": ("error · LLM", "The LLM call failed (timeout, connection, HTTP error).", "llm", "LLM"),
    "excluded": ("excluded", "An exclusion rule matches this container, so its logs are not read.", None, "Exclusions"),
    "container_event": ("lifecycle", "Docker lifecycle signal (die / oom / restart), not a log chunk.", "alerts", "Restart-storm"),
}

# alert_error prefixes -> (label, settings anchor, knob label)
SUPPRESSION_KNOBS: list[tuple[str, str, str | None, str]] = [
    ("muted until", "muted", None, "Mute"),
    ("duplicate alert suppressed by cooldown", "alert cooldown", "alerts", "Alert cooldown"),
    ("confidence", "confidence gate", "alerts", "Min confidence"),
    ("suppressed: recently rejected", "rejected issue", None, "Rejected issue (24 h)"),
    ("global rate limit", "global rate limit", "limits", "Alert rate-limit"),
    ("persistent warning alert suppressed", "escalation cooldown", "alerts", "Escalation window"),
    ("restart storm alert suppressed", "storm cooldown", "alerts", "Restart-storm window"),
]


def explain_status(status: str | None) -> dict[str, str | None]:
    label, why, anchor, knob = STATUS_EXPLAIN.get(status or "", (status or "—", "", None, None))
    return {"label": label, "why": why, "anchor": anchor, "knob": knob}


def explain_suppression(alert_error: str | None) -> dict[str, str | None] | None:
    if not alert_error:
        return None
    low = alert_error.lower()
    for prefix, label, anchor, knob in SUPPRESSION_KNOBS:
        if prefix in low:
            return {"label": label, "anchor": anchor, "knob": knob, "raw": alert_error}
    return {"label": "not delivered", "anchor": "alerts", "knob": "Telegram", "raw": alert_error}


def below_threshold(event: AnalysisEvent, settings: Settings) -> bool:
    """analyzed but classification under alert_min_classification → never eligible."""
    return classification_rank(event.classification) < classification_rank(settings.alert_min_classification)


def alert_outcome(event: AnalysisEvent, settings: Settings) -> dict[str, str | None]:
    """One line answering 'did this alert, and if not, why not?'."""
    if event.alert_sent:
        return {"kind": "sent", "label": "alerted on Telegram", "why": None, "anchor": None}
    if event.status == "analyzed":
        if event.alert_error:
            s = explain_suppression(event.alert_error) or {}
            return {"kind": "suppressed", "label": f"suppressed · {s.get('label')}", "why": event.alert_error, "anchor": s.get("anchor")}
        if below_threshold(event, settings):
            return {
                "kind": "below",
                "label": f"below alert threshold ({settings.alert_min_classification})",
                "why": f"Verdict '{event.classification}' is under 'Alert on classification ≥ {settings.alert_min_classification}'.",
                "anchor": "alerts",
            }
        return {"kind": "none", "label": "not alerted", "why": None, "anchor": None}
    if event.status == "container_event":
        if event.alert_error:
            return {"kind": "suppressed", "label": "storm alert suppressed", "why": event.alert_error, "anchor": "alerts"}
        return {"kind": "none", "label": "lifecycle only", "why": None, "anchor": None}
    e = explain_status(event.status)
    return {"kind": "never", "label": "never reached the LLM", "why": e["why"], "anchor": e["anchor"]}


@dataclass
class FunnelStage:
    key: str
    label: str
    count: int
    dropped: int
    knob: str | None
    anchor: str | None
    reason: str


@dataclass
class ContainerFunnel:
    stages: list[FunnelStage] = field(default_factory=list)
    suppressions: list[tuple[str, int, str | None]] = field(default_factory=list)  # label, n, anchor
    lifecycle: int = 0
    excluded: int = 0
    total_chunks: int = 0
    alerted: int = 0


def build_funnel(events: Iterable[AnalysisEvent], settings: Settings) -> ContainerFunnel:
    """Fold a container's events into the seen → … → alerted funnel."""
    by_status: Counter[str] = Counter()
    supp: Counter[str] = Counter()
    supp_anchor: dict[str, str | None] = {}
    below = 0
    alerted = 0
    for e in events:
        by_status[e.status] += 1
        if e.status == "analyzed":
            if e.alert_sent:
                alerted += 1
            elif e.alert_error:
                s = explain_suppression(e.alert_error) or {}
                lbl = str(s.get("label"))
                supp[lbl] += 1
                supp_anchor[lbl] = s.get("anchor")
            elif below_threshold(e, settings):
                below += 1

    f = ContainerFunnel()
    f.lifecycle = by_status["container_event"]
    f.excluded = by_status["excluded"]
    chunks = sum(v for k, v in by_status.items() if k not in {"container_event", "excluded"})
    f.total_chunks = chunks
    f.alerted = alerted

    remaining = chunks

    def stage(key: str, label: str, dropped: int, knob: str | None, anchor: str | None, reason: str) -> None:
        nonlocal remaining
        f.stages.append(FunnelStage(key, label, remaining, dropped, knob, anchor, reason))
        remaining -= dropped

    stage("seen", "log chunks seen", by_status["skipped"], "Keyword list", "budgets",
          "chunks with no keyword hit are dropped before the LLM")
    stage("keyword", "matched a keyword", by_status["dedup_skipped"], "Dedup window", "limits",
          "identical chunks inside the window are dropped")
    stage("unique", "not a duplicate", by_status["rate_limited"], "Container rate limit", "limits",
          "over the per-container LLM-call budget")
    stage("budget", "inside rate budget", by_status["queued"], "Coalesce window", "limits",
          "held to be merged with neighbours (queued)")
    stage("coalesce", "released to analysis", by_status["analysis_cooldown"], "Analysis cooldown", "alerts",
          "same-looking as the previous verdict; verdict inherited, LLM not called")
    stage("cooldown", "sent to the LLM", by_status["llm_error"] + by_status["parse_error"], "LLM", "llm",
          "LLM call failed or reply was unparseable")
    analyzed = by_status["analyzed"]
    stage("analyzed", "classified by the LLM", below, "Alert on classification ≥", "alerts",
          "verdict below the alert threshold (noise/warning)")
    suppressed_total = sum(supp.values())
    stage("eligible", "alert-worthy", suppressed_total, "Cooldown / mute / confidence", "alerts",
          "held back by a suppression rule")
    f.stages.append(FunnelStage("alerted", "alerted on Telegram", alerted, 0, None, None, ""))
    # guard against inconsistent history (e.g. analyzed rows with neither flag)
    for s in f.stages:
        if s.count < 0:
            s.count = 0
    f.suppressions = sorted(((k, v, supp_anchor.get(k)) for k, v in supp.items()), key=lambda t: -t[1])
    return f


def tuning_impact(events: Iterable[AnalysisEvent]) -> dict[str, int]:
    """Counts the Settings page shows next to each noise knob ("what did it do?")."""
    c: Counter[str] = Counter()
    for e in events:
        c[e.status] += 1
        if e.status == "analyzed" and not e.alert_sent and e.alert_error:
            s = explain_suppression(e.alert_error) or {}
            c["supp:" + str(s.get("label"))] += 1
        if e.status == "analyzed" and e.alert_sent:
            c["alerted"] += 1
        if e.status == "container_event" and e.alert_sent:
            c["storm_alerted"] += 1
    return dict(c)


def worst_classification(a: str | None, b: str | None) -> str | None:
    return a if classification_rank(a) >= classification_rank(b) else b
