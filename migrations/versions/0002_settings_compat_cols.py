"""add settings compat columns

Revision ID: 8b3f1a2c9d45
Revises: 5ca5251db402
Create Date: 2026-04-04 19:30:00.000000
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa

revision: str = '8b3f1a2c9d45'
down_revision: str = '5ca5251db402'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("llm_transport", sa.String(16), nullable=False, server_default="api"))
        batch_op.add_column(sa.Column("cli_backend", sa.String(64), nullable=False, server_default="codex"))
        batch_op.add_column(sa.Column("cli_timeout_seconds", sa.Integer(), nullable=False, server_default="120"))
        batch_op.add_column(sa.Column("cli_max_retries", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("dedup_window_seconds", sa.Integer(), nullable=False, server_default="300"))
        batch_op.add_column(sa.Column("container_rate_limit_count", sa.Integer(), nullable=False, server_default="10"))
        batch_op.add_column(sa.Column("container_rate_limit_window_seconds", sa.Integer(), nullable=False, server_default="3600"))
        batch_op.add_column(sa.Column("keyword_flush_delay_lines", sa.Integer(), nullable=False, server_default="5"))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("keyword_flush_delay_lines")
        batch_op.drop_column("container_rate_limit_window_seconds")
        batch_op.drop_column("container_rate_limit_count")
        batch_op.drop_column("dedup_window_seconds")
        batch_op.drop_column("cli_max_retries")
        batch_op.drop_column("cli_timeout_seconds")
        batch_op.drop_column("cli_backend")
        batch_op.drop_column("llm_transport")
