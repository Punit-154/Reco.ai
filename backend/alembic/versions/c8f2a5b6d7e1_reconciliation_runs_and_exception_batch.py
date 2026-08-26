"""reconciliation runs and exception batch linkage

Revision ID: c8f2a5b6d7e1
Revises: b7c4d1e93a52
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c8f2a5b6d7e1'
down_revision: Union[str, None] = 'b7c4d1e93a52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reconciliation_runs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_runs')),
    )
    op.create_index(
        op.f('ix_reconciliation_runs_org_id'), 'reconciliation_runs', ['org_id'], unique=False
    )
    op.add_column(
        'exceptions',
        sa.Column('batch_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'fk_exceptions_batch_id_reconciliation_runs',
        'exceptions',
        'reconciliation_runs',
        ['batch_id'],
        ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        op.f('ix_exceptions_batch_id'), 'exceptions', ['batch_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_exceptions_batch_id'), table_name='exceptions')
    op.drop_column('exceptions', 'batch_id')
    op.drop_index(op.f('ix_reconciliation_runs_org_id'), table_name='reconciliation_runs')
    op.drop_table('reconciliation_runs')
