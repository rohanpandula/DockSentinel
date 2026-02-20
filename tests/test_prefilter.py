from __future__ import annotations

from app.services.prefilter import Prefilter


def test_prefilter_matches_keywords_case_insensitive():
    pf = Prefilter(["error", "timeout", "fatal"])
    matches = pf.match("Request TIMEOUT after unknown Error")
    assert sorted(matches) == ["error", "timeout"]


def test_prefilter_no_match():
    pf = Prefilter(["panic"])
    assert pf.match("all systems nominal") == []


def test_prefilter_rejects_json_benign_values():
    """'error' inside '{"error":0}' should not match."""
    pf = Prefilter(["error", "timeout"])
    assert pf.match('{"error":0, "timeout":0}') == []
    assert pf.match('{"error": 0, "requests": 42}') == []
    assert pf.match('{"error": false}') == []
    assert pf.match('{"error": null}') == []


def test_prefilter_rejects_compound_identifiers():
    """'error' inside 'error_count' should not match (underscore is a word char)."""
    pf = Prefilter(["error"])
    assert pf.match("error_count=5 is_error_free=true") == []


def test_prefilter_matches_real_error_in_json():
    """'error' in '"error":"connection refused"' should match."""
    pf = Prefilter(["error"])
    assert pf.match('{"error":"connection refused"}') == ["error"]


def test_prefilter_mixed_benign_and_real():
    """When text has both benign and real keyword occurrences."""
    pf = Prefilter(["error"])
    text = '{"error":0} followed by ERROR: connection refused'
    result = pf.match(text)
    assert result == ["error"]


def test_prefilter_word_boundary_basic():
    """Keywords should match as whole words."""
    pf = Prefilter(["error"])
    assert pf.match("An error occurred") == ["error"]
    assert pf.match("ERROR: disk full") == ["error"]
