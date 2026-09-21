"""add restart-storm alert settings

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-15 12:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: str = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("restart_alert_count", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("restart_alert_window_minutes", sa.Integer(), nullable=False, server_default="10"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("restart_alert_window_minutes")
        batch_op.drop_column("restart_alert_count")
