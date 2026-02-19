from __future__ import annotations

from app.services.prefilter import Prefilter


def test_prefilter_matches_keywords_case_insensitive():
    pf = Prefilter(["error", "timeout", "fatal"])
    matches = pf.match("Request TIMEOUT after unknown Error")
    assert sorted(matches) == ["error", "timeout"]


def test_prefilter_no_match():
    pf = Prefilter(["panic"])
    assert pf.match("all systems nominal") == []
