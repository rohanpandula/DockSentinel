from __future__ import annotations

from app.extensions import db
from app.models.exclusions import ExclusionRule


class ExclusionRepository:
    def list_enabled(self) -> list[ExclusionRule]:
        return ExclusionRule.query.filter_by(enabled=True).all()

    def list_all(self) -> list[ExclusionRule]:
        return ExclusionRule.query.order_by(ExclusionRule.container_pattern.asc()).all()

    def find_by_pattern(self, pattern: str) -> ExclusionRule | None:
        return ExclusionRule.query.filter_by(container_pattern=pattern).first()

    def get(self, rule_id: int) -> ExclusionRule | None:
        return db.session.get(ExclusionRule, rule_id)

    def add(self, rule: ExclusionRule) -> None:
        db.session.add(rule)

    def delete(self, rule: ExclusionRule) -> None:
        db.session.delete(rule)
