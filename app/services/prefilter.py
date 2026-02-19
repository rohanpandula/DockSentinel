from __future__ import annotations


class Prefilter:
    def __init__(self, keywords: list[str]) -> None:
        self.keywords = [k.strip().lower() for k in keywords if k and k.strip()]

    def match(self, text: str) -> list[str]:
        lowered = text.lower()
        return [keyword for keyword in self.keywords if keyword in lowered]
