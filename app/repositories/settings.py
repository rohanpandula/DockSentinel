from __future__ import annotations

from app.extensions import db
from app.models.settings import Settings


class SettingsRepository:
    def get(self) -> Settings:
        return Settings.singleton()

    def save(self) -> None:
        db.session.commit()
