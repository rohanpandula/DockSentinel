"""initial schema

Revision ID: 5ca5251db402
Revises:
Create Date: 2026-04-04 19:29:04.180177
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa


revision: str = '5ca5251db402'
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table('analysis_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('container_id', sa.String(length=128), nullable=True),
    sa.Column('container_name', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('classification', sa.String(length=32), nullable=True),
    sa.Column('matched_keywords', sa.String(length=512), nullable=True),
    sa.Column('chunk_hash', sa.String(length=64), nullable=True),
    sa.Column('chunk_excerpt', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('root_cause_hypothesis', sa.Text(), nullable=True),
    sa.Column('fix_suggestion', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('input_chars', sa.Integer(), nullable=True),
    sa.Column('estimated_input_tokens', sa.Integer(), nullable=True),
    sa.Column('latency_ms', sa.Integer(), nullable=True),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('prompt_version', sa.Integer(), nullable=True),
    sa.Column('llm_error', sa.Text(), nullable=True),
    sa.Column('parse_error', sa.Text(), nullable=True),
    sa.Column('alert_sent', sa.Boolean(), nullable=False),
    sa.Column('alert_error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('analysis_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_analysis_events_chunk_hash'), ['chunk_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_events_classification'), ['classification'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_events_container_id'), ['container_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_events_container_name'), ['container_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_analysis_events_status'), ['status'], unique=False)

    op.create_table('daily_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('period_start', sa.DateTime(), nullable=False),
    sa.Column('period_end', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('markdown_content', sa.Text(), nullable=False),
    sa.Column('model', sa.String(length=255), nullable=True),
    sa.Column('prompt_version', sa.Integer(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('daily_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_daily_reports_created_at'), ['created_at'], unique=False)

    op.create_table('exclusion_rules',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('container_pattern', sa.String(length=255), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('container_pattern')
    )
    op.create_table('prompt_templates',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('default_content', sa.Text(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('schema_version',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sentinel_state',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('runtime_status', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('last_error', sa.Text(), nullable=True),
    sa.Column('llm_failure_count', sa.Integer(), nullable=False),
    sa.Column('llm_last_failure_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('llm_base_url', sa.String(length=255), nullable=False),
    sa.Column('llm_api_key', sa.String(length=255), nullable=False),
    sa.Column('llm_model', sa.String(length=255), nullable=False),
    sa.Column('llm_provider', sa.String(length=64), nullable=False),
    sa.Column('telegram_token', sa.String(length=255), nullable=True),
    sa.Column('telegram_chat_id', sa.String(length=255), nullable=True),
    sa.Column('nightly_hour', sa.Integer(), nullable=False),
    sa.Column('nightly_minute', sa.Integer(), nullable=False),
    sa.Column('max_input_chars', sa.Integer(), nullable=False),
    sa.Column('max_input_tokens', sa.Integer(), nullable=False),
    sa.Column('reserved_output_tokens', sa.Integer(), nullable=False),
    sa.Column('token_estimation_strategy', sa.String(length=32), nullable=False),
    sa.Column('keyword_list', sa.Text(), nullable=False),
    sa.Column('alert_cooldown_minutes', sa.Integer(), nullable=False),
    sa.Column('alert_rate_limit_count', sa.Integer(), nullable=False),
    sa.Column('alert_rate_limit_window_seconds', sa.Integer(), nullable=False),
    sa.Column('llm_timeout_seconds', sa.Integer(), nullable=False),
    sa.Column('llm_max_retries', sa.Integer(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('settings')
    op.drop_table('sentinel_state')
    op.drop_table('schema_version')
    op.drop_table('prompt_templates')
    op.drop_table('exclusion_rules')
    with op.batch_alter_table('daily_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_daily_reports_created_at'))

    op.drop_table('daily_reports')
    with op.batch_alter_table('analysis_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_analysis_events_status'))
        batch_op.drop_index(batch_op.f('ix_analysis_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_analysis_events_container_name'))
        batch_op.drop_index(batch_op.f('ix_analysis_events_container_id'))
        batch_op.drop_index(batch_op.f('ix_analysis_events_classification'))
        batch_op.drop_index(batch_op.f('ix_analysis_events_chunk_hash'))

    op.drop_table('analysis_events')
