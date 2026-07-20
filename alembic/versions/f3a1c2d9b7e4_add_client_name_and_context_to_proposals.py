"""add client_name and additional_context to proposals

Revision ID: f3a1c2d9b7e4
Revises: 872db9f9115a
Create Date: 2026-07-20 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f3a1c2d9b7e4'
down_revision: Union[str, Sequence[str], None] = '872db9f9115a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('proposals', sa.Column('client_name', sa.String(length=255), nullable=False, server_default=''))
    op.add_column('proposals', sa.Column('additional_context', sa.Text(), nullable=True))
    op.alter_column('proposals', 'client_name', server_default=None)


def downgrade() -> None:
    op.drop_column('proposals', 'additional_context')
    op.drop_column('proposals', 'client_name')
