"""add composite indexes to audit_logs for filter query performance

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-12

"""
from alembic import op

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'idx_audit_action_created',
        'audit_logs', ['action', 'created_at'],
    )
    op.create_index(
        'idx_audit_table_action_created',
        'audit_logs', ['table_name', 'action', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('idx_audit_table_action_created', table_name='audit_logs')
    op.drop_index('idx_audit_action_created', table_name='audit_logs')
