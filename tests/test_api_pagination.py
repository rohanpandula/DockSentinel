from __future__ import annotations


def test_insights_no_params_returns_items_envelope(client):
    resp = client.get("/api/insights")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "items" in body
    assert isinstance(body["items"], list)
    # offset/limit are new top-level keys — additive per API-04
    assert body["offset"] == 0
    assert body["limit"] == 100


def test_insights_limit_above_cap_returns_error_envelope(client):
    resp = client.get("/api/insights?limit=501")
    assert resp.status_code == 400
    body = resp.get_json()
    assert "error" in body
    assert "validation_error" not in body  # remap to codebase convention


def test_insights_negative_offset_returns_error_envelope(client):
    resp = client.get("/api/insights?offset=-1")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_insights_non_integer_limit_returns_error_envelope(client):
    resp = client.get("/api/insights?limit=abc")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_insights_bogus_sort_returns_error_envelope(client):
    resp = client.get("/api/insights?sort=bogus")
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_insights_valid_sort_ascending(client):
    resp = client.get("/api/insights?sort=created_at")
    assert resp.status_code == 200


def test_reports_no_params_returns_items_envelope(client):
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "items" in body
    assert body["offset"] == 0
    assert body["limit"] == 100


def test_reports_limit_above_cap_returns_error_envelope(client):
    resp = client.get("/api/reports?limit=501")
    assert resp.status_code == 400
    assert "error" in resp.get_json()
