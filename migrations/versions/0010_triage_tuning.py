"""add triage tuning columns to settings

analysis_cooldown_minutes, persistent_warning_count,
persistent_warning_window_minutes, alert_min_confidence

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: str = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("analysis_cooldown_minutes", sa.Integer(), nullable=False, server_default="15"))
        batch_op.add_column(sa.Column("persistent_warning_count", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(
            sa.Column("persistent_warning_window_minutes", sa.Integer(), nullable=False, server_default="60")
        )
        batch_op.add_column(sa.Column("alert_min_confidence", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("alert_min_confidence")
        batch_op.drop_column("persistent_warning_window_minutes")
        batch_op.drop_column("persistent_warning_count")
        batch_op.drop_column("analysis_cooldown_minutes")
