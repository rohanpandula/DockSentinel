from __future__ import annotations

import re


class Prefilter:
    """Keyword prefilter with word-boundary matching and JSON false-positive suppression.

    Uses ``\\b`` word-boundary regex so that ``"error"`` does **not** match
    inside compound identifiers like ``error_count`` (Python ``\\b`` treats
    ``_`` as a word character).  A second pass detects JSON patterns where the
    keyword is a key with a benign zero/false/null value (e.g.
    ``"error":0``); if *every* occurrence in the text is benign the keyword
    is excluded from the hit list.
    """

    def __init__(self, keywords: list[str]) -> None:
        self.keywords = [k.strip().lower() for k in keywords if k and k.strip()]
        # Pre-compile one word-boundary regex per keyword.
        self._word_re: dict[str, re.Pattern[str]] = {
            kw: re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
            for kw in self.keywords
        }
        # Pre-compile one "benign JSON value" regex per keyword.
        # Matches patterns like: "error":0  "error": false  "error":null
        self._benign_re: dict[str, re.Pattern[str]] = {
            kw: re.compile(
                r'"' + re.escape(kw) + r'"\s*:\s*(0|false|null)\b',
                re.IGNORECASE,
            )
            for kw in self.keywords
        }

    def match(self, text: str) -> list[str]:
        hits: list[str] = []
        for kw in self.keywords:
            word_matches = self._word_re[kw].findall(text)
            if not word_matches:
                continue
            # Count how many occurrences are benign JSON key:value patterns.
            benign_count = len(self._benign_re[kw].findall(text))
            if benign_count > 0 and benign_count >= len(word_matches):
                continue
            hits.append(kw)
        return hits
