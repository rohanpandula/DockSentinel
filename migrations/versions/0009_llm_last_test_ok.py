"""add llm_last_test_ok_at to sentinel_state

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: str = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sentinel_state") as batch_op:
        batch_op.add_column(sa.Column("llm_last_test_ok_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("sentinel_state") as batch_op:
        batch_op.drop_column("llm_last_test_ok_at")
