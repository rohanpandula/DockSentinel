from __future__ import annotations

from app.extensions import db


class SchemaVersion(db.Model):
    __tablename__ = "schema_version"

    id = db.Column(db.Integer, primary_key=True, default=1)
    version = db.Column(db.Integer, nullable=False, default=1)

    @classmethod
    def singleton(cls) -> "SchemaVersion":
        row = db.session.get(cls, 1)
        if row is None:
            row = cls(id=1, version=1)
            db.session.add(row)
            db.session.commit()
        return row
