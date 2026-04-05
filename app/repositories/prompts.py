from __future__ import annotations

from app.models.prompts import PromptKey, PromptTemplate


class PromptRepository:
    def get_by_key(self, key: PromptKey | str) -> PromptTemplate | None:
        key_value = key.value if isinstance(key, PromptKey) else key
        return PromptTemplate.query.filter_by(key=key_value).first()

    def list_all(self) -> list[PromptTemplate]:
        return PromptTemplate.query.order_by(PromptTemplate.key.asc()).all()
