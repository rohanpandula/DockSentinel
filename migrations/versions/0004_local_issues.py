"""create local_issues table

Revision ID: b82e1f4a5c66
Revises: a71f0c2d3e10
Create Date: 2026-04-14 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'b82e1f4a5c66'
down_revision: str = 'a71f0c2d3e10'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_issues",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("analysis_events.id"), nullable=True),
        sa.Column("container_name", sa.String(255), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("telegram_chat_id", sa.String(255), nullable=True),
        sa.Column("telegram_message_id", sa.Integer(), nullable=True),
        sa.Column("discussion", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_local_issues_event_id", "local_issues", ["event_id"])
    op.create_index("ix_local_issues_status", "local_issues", ["status"])
    op.create_index("ix_local_issues_telegram_message_id", "local_issues", ["telegram_message_id"])


def downgrade() -> None:
    op.drop_index("ix_local_issues_telegram_message_id", table_name="local_issues")
    op.drop_index("ix_local_issues_status", table_name="local_issues")
    op.drop_index("ix_local_issues_event_id", table_name="local_issues")
    op.drop_table("local_issues")
