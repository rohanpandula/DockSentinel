"""add llm_model column to local_issues

Revision ID: c9a0d7f2e411
Revises: b82e1f4a5c66
Create Date: 2026-04-14 00:00:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = 'c9a0d7f2e411'
down_revision: str = 'b82e1f4a5c66'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("local_issues") as batch_op:
        batch_op.add_column(sa.Column("llm_model", sa.String(255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("local_issues") as batch_op:
        batch_op.drop_column("llm_model")
