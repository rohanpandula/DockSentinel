"""add chunk_coalesce_window_seconds to settings

Revision ID: a71f0c2d3e10
Revises: 8b3f1a2c9d45
Create Date: 2026-04-14 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'a71f0c2d3e10'
down_revision: str = '8b3f1a2c9d45'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("chunk_coalesce_window_seconds", sa.Integer(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("chunk_coalesce_window_seconds")
