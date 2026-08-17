"""add incidents table + incident notification settings

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: str = 'f6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signature", sa.String(length=64), nullable=False),
        sa.Column("container_name", sa.String(length=255), nullable=False),
        sa.Column("classification", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("telegram_chat_id", sa.String(length=255), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(), nullable=True),
        sa.Column("notify_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_incidents_signature", "incidents", ["signature"])
    op.create_index("ix_incidents_container_name", "incidents", ["container_name"])
    op.create_index("ix_incidents_status", "incidents", ["status"])

    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column(
                "incident_resolve_after_minutes",
                sa.Integer(),
                nullable=False,
                server_default="30",
            )
        )
        batch.add_column(
            sa.Column(
                "incident_reminder_hours", sa.Integer(), nullable=False, server_default="0"
            )
        )
        batch.add_column(
            sa.Column(
                "incident_notify_on_resolve",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("incident_notify_on_resolve")
        batch.drop_column("incident_reminder_hours")
        batch.drop_column("incident_resolve_after_minutes")

    op.drop_index("ix_incidents_status", table_name="incidents")
    op.drop_index("ix_incidents_container_name", table_name="incidents")
    op.drop_index("ix_incidents_signature", table_name="incidents")
    op.drop_table("incidents")
