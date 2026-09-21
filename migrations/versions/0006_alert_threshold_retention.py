"""add alert_min_classification and event_retention_days to settings

Revision ID: a1b2c3d4e5f6
Revises: c9a0d7f2e411
Create Date: 2026-08-15 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: str = 'c9a0d7f2e411'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("alert_min_classification", sa.String(16), nullable=False, server_default="critical"))
        batch_op.add_column(sa.Column("event_retention_days", sa.Integer(), nullable=False, server_default="14"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("event_retention_days")
        batch_op.drop_column("alert_min_classification")
