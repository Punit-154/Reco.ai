"""sources unique (org_id, kind, name)

Revision ID: b7c4d1e93a52
Revises: 0951bb2d2731
Create Date: 2026-08-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7c4d1e93a52'
down_revision: Union[str, None] = '0951bb2d2731'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_sources_org_kind_name', 'sources', ['org_id', 'kind', 'name']
    )


def downgrade() -> None:
    op.drop_constraint('uq_sources_org_kind_name', 'sources', type_='unique')
