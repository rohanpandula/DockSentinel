from __future__ import annotations

from app.extensions import db
from app.models import (
    DEFAULT_PROMPTS,
    ExclusionRule,
    PromptTemplate,
    SchemaVersion,
    SentinelState,
    Settings,
)


def seed_defaults() -> None:
    SchemaVersion.singleton()
    Settings.singleton()
    SentinelState.singleton()

    for pattern in ["docksentinel", "ollama", "portainer", "open-webui"]:
        if ExclusionRule.query.filter_by(container_pattern=pattern).first() is None:
            db.session.add(ExclusionRule(container_pattern=pattern, enabled=True))

    for key, content in DEFAULT_PROMPTS.items():
        existing = PromptTemplate.query.filter_by(key=key.value).first()
        if existing is None:
            db.session.add(
                PromptTemplate(
                    key=key.value,
                    content=content,
                    default_content=content,
                    version=1,
                    is_default=True,
                )
            )
        elif existing.default_content != content:
            # Ship updated defaults to existing DBs: always refresh the stored
            # default (so "Reset" gives the new text) and, if the operator never
            # customised the prompt, the live content too.
            existing.default_content = content
            if existing.is_default:
                existing.content = content
                existing.version = (existing.version or 1) + 1

    db.session.commit()
