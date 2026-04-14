from __future__ import annotations

import pytest

from app.schemas.insights import InsightItem
from app.schemas.reports import ReportItem


# Frozen reference lists — change these ONLY if you intend to change the
# API wire format. Mirrors AnalysisEvent.as_dict / DailyReport.as_dict.

INSIGHT_KEYS = {
    "id", "created_at", "container_id", "container_name", "status",
    "classification", "matched_keywords", "chunk_hash", "chunk_excerpt",
    "summary", "root_cause_hypothesis", "fix_suggestion", "confidence",
    "input_chars", "estimated_input_tokens", "latency_ms", "model",
    "prompt_version", "llm_error", "parse_error", "alert_sent", "alert_error",
}

REPORT_KEYS = {
    "id", "created_at", "period_start", "period_end", "status",
    "markdown_content", "model", "prompt_version", "error",
}


def test_insight_schema_fields_match_as_dict_exactly():
    assert set(InsightItem.model_fields.keys()) == INSIGHT_KEYS


def test_report_schema_fields_match_as_dict_exactly():
    assert set(ReportItem.model_fields.keys()) == REPORT_KEYS


def test_insights_list_response_items_shape_matches_as_dict(client, container, db_session):
    """Parity check: one seeded event, GET /api/insights returns the same keys
    as AnalysisEvent.as_dict() — no new keys, no dropped keys inside items[]."""
    from app.models.events import AnalysisEvent
    from app.time_utils import utcnow_naive

    event = AnalysisEvent(
        container_id="cid",
        container_name="web",
        status="analyzed",
        classification="info",
        chunk_excerpt="hello",
        alert_sent=False,
        created_at=utcnow_naive(),
    )
    db_session.add(event)
    db_session.commit()

    resp = client.get("/api/insights?limit=5")
    assert resp.status_code == 200
    items = resp.get_json()["items"]
    assert items, "seeded event should appear"
    # Key parity with as_dict() — API-04 backward compatibility anchor
    assert set(items[0].keys()) == set(event.as_dict().keys())


def test_settings_endpoint_keys_preserved(client):
    """Guards tests/test_api.py:103-121 — Pitfall P-07. The schema must not
    drop any Settings.as_dict key (e.g., dedup_window_seconds)."""
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.get_json()
    required = {
        "dedup_window_seconds",
        "container_rate_limit_count",
        "container_rate_limit_window_seconds",
        "keyword_flush_delay_lines",
        "llm_base_url",
        "llm_model",
        "telegram_chat_id",
        "alert_cooldown_minutes",
    }
    missing = required - set(body.keys())
    assert not missing, f"settings response missing keys: {missing}"


# --- Per-endpoint wire-format parity tests (blocker fix) ---
# These assert that each endpoint returns the exact same top-level key set as
# the corresponding pre-Phase-5 ORM.as_dict() / frozen manual dict. Catches
# silent field-drift across all 8 blueprints (API-04 guard).


def test_list_endpoint_items_shape_parity(client, container, db_session):
    """Seed one row per list endpoint, assert items[0].keys() matches
    the pre-Phase-5 as_dict() key set exactly. Covers /api/insights and
    /api/reports."""
    from app.models.events import AnalysisEvent
    from app.models.reports import DailyReport
    from app.time_utils import utcnow_naive

    # --- Seed one AnalysisEvent for /api/insights ---
    ev = AnalysisEvent(
        container_id="cid-list",
        container_name="api-list-insights",
        status="analyzed",
        classification="info",
        chunk_excerpt="list-parity",
        alert_sent=False,
        created_at=utcnow_naive(),
    )
    db_session.add(ev)

    # --- Seed one DailyReport for /api/reports ---
    rep = DailyReport(
        period_start=utcnow_naive(),
        period_end=utcnow_naive(),
        status="completed",
        markdown_content="# parity test",
        created_at=utcnow_naive(),
    )
    db_session.add(rep)
    db_session.commit()

    r_ins = client.get("/api/insights?limit=5")
    assert r_ins.status_code == 200
    ins_items = r_ins.get_json()["items"]
    assert ins_items, "seeded insight should appear"
    assert set(ins_items[0].keys()) == set(ev.as_dict().keys()), (
        f"insights items[0] keys drifted from AnalysisEvent.as_dict: "
        f"extra={set(ins_items[0].keys()) - set(ev.as_dict().keys())} "
        f"missing={set(ev.as_dict().keys()) - set(ins_items[0].keys())}"
    )

    r_rep = client.get("/api/reports?limit=5")
    assert r_rep.status_code == 200
    rep_items = r_rep.get_json()["items"]
    assert rep_items, "seeded report should appear"
    assert set(rep_items[0].keys()) == set(rep.as_dict().keys()), (
        f"reports items[0] keys drifted from DailyReport.as_dict: "
        f"extra={set(rep_items[0].keys()) - set(rep.as_dict().keys())} "
        f"missing={set(rep.as_dict().keys()) - set(rep_items[0].keys())}"
    )


def test_mutation_endpoint_shape_parity(client, container, db_session):
    """Seed one row per mutation/status endpoint, hit the detail/status GET,
    assert top-level key set == as_dict() key set (or the frozen manual dict
    for endpoints without an ORM source).

    Covers: /api/exclusions list, /api/prompts list, /api/settings GET,
    /api/sentinel/status state, /api/health runtime sub-dict, /api/telegram/test
    shape-frozen-by-schema."""
    from app.models.exclusions import ExclusionRule
    from app.models.prompts import PromptTemplate as Prompt
    from app.models.settings import Settings
    from app.models.sentinel_state import SentinelState
    from app.time_utils import utcnow_naive

    # --- /api/exclusions ---
    rule = ExclusionRule(container_pattern="parity-*", enabled=True)
    db_session.add(rule)
    db_session.commit()
    r_exc = client.get("/api/exclusions")
    assert r_exc.status_code == 200
    exc_items = r_exc.get_json()["items"]
    assert exc_items, "seeded exclusion should appear"
    assert set(exc_items[0].keys()) == set(rule.as_dict().keys()), (
        f"exclusions keys drifted: "
        f"extra={set(exc_items[0].keys()) - set(rule.as_dict().keys())} "
        f"missing={set(rule.as_dict().keys()) - set(exc_items[0].keys())}"
    )

    # --- /api/prompts ---
    r_pr = client.get("/api/prompts")
    assert r_pr.status_code == 200
    pr_items = r_pr.get_json()["items"]
    if pr_items:
        pr_obj = Prompt.query.filter_by(key=pr_items[0]["key"]).first()
        assert pr_obj is not None
        assert set(pr_items[0].keys()) == set(pr_obj.as_dict().keys()), (
            f"prompts keys drifted: "
            f"extra={set(pr_items[0].keys()) - set(pr_obj.as_dict().keys())} "
            f"missing={set(pr_obj.as_dict().keys()) - set(pr_items[0].keys())}"
        )

    # --- /api/settings ---
    r_set = client.get("/api/settings")
    assert r_set.status_code == 200
    settings_body = r_set.get_json()
    settings_obj = Settings.singleton()
    assert set(settings_body.keys()) == set(settings_obj.as_dict().keys()), (
        f"settings keys drifted: "
        f"extra={set(settings_body.keys()) - set(settings_obj.as_dict().keys())} "
        f"missing={set(settings_obj.as_dict().keys()) - set(settings_body.keys())}"
    )

    # --- /api/sentinel/status state.state — state dict must match SentinelState.as_dict ---
    # Route is /api/sentinel/status (not /api/sentinel)
    r_sen = client.get("/api/sentinel/status")
    assert r_sen.status_code == 200
    sen_body = r_sen.get_json()
    assert "state" in sen_body, "sentinel status response should include 'state'"
    sen_obj = SentinelState.singleton()
    assert set(sen_body["state"].keys()) == set(sen_obj.as_dict().keys()), (
        f"sentinel state keys drifted: "
        f"extra={set(sen_body['state'].keys()) - set(sen_obj.as_dict().keys())} "
        f"missing={set(sen_obj.as_dict().keys()) - set(sen_body['state'].keys())}"
    )

    # --- /api/health — frozen top-level {"status", "runtime"}; runtime matches SentinelState.as_dict ---
    r_h = client.get("/api/health")
    assert r_h.status_code == 200
    h_body = r_h.get_json()
    assert set(h_body.keys()) == {"status", "runtime"}, (
        f"health top-level keys drifted: {set(h_body.keys())}"
    )
    assert set(h_body["runtime"].keys()) == set(sen_obj.as_dict().keys()), (
        f"health.runtime keys drifted from SentinelState.as_dict"
    )

    # --- /api/telegram/test — shape-frozen-by-schema (no ORM; key set {ok, error}) ---
    # Use POST; body is not required by current route. Response shape is frozen
    # regardless of outcome (success or misconfig).
    r_tg = client.post("/api/telegram/test", json={})
    # Accept 200 or 400/500 — we only assert the response SHAPE is stable.
    tg_body = r_tg.get_json() or {}
    # When validation fails we return {"error": ...}; when the endpoint
    # executes we return {"ok": bool, "error": str | None}. Both are acceptable
    # — the guard is "no other unexpected keys".
    allowed = {"ok", "error"}
    assert set(tg_body.keys()).issubset(allowed), (
        f"telegram/test returned unexpected keys: {set(tg_body.keys()) - allowed}"
    )
