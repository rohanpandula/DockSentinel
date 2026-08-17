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


def test_prefilter_multiword_phrase_matches_as_phrase():
    pf = Prefilter(["out of memory", "oom"])
    assert pf.match("kernel: Out of memory: Killed process 1234") == ["out of memory"]
    assert pf.match("container ran out  of\tmemory") == ["out of memory"]
    assert pf.match("out of disk, memory fine") == []
    assert pf.match("oom-killer invoked") == ["oom"]
    assert pf.match("zoom in") == []


def test_default_keyword_list_covers_common_errors():
    from app.models.settings import DEFAULT_KEYWORD_LIST

    pf = Prefilter(DEFAULT_KEYWORD_LIST.split(","))
    assert "traceback" in pf.match("Traceback (most recent call last):")
    assert "failed" in pf.match("Failed to connect to db")
    assert "denied" in pf.match("permission denied")
    assert "killed" in pf.match("process killed")
    assert "unhealthy" in pf.match("container is unhealthy")
    assert "segfault" in pf.match("segfault at 0 ip 0000")
    assert "out of memory" in pf.match("Out of memory: Killed process")
    assert pf.match("timeout_ms=30 error_count=0") == []
