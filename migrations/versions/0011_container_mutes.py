"""add container_mutes table (per-container alert mute)

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: str = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "container_mutes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("container_name", sa.String(length=255), nullable=False),
        sa.Column("until", sa.DateTime(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_container_mutes_container_name", "container_mutes", ["container_name"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_container_mutes_container_name", table_name="container_mutes")
    op.drop_table("container_mutes")
