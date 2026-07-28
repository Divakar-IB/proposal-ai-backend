"""add is_approved and approved_markdown to proposals

Revision ID: e3f4a5b6c7d8
Revises: d7e8f9a0b1c2
Create Date: 2026-07-22 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, Sequence[str], None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'proposals', sa.Column('is_approved', sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.alter_column('proposals', 'is_approved', server_default=None)
    op.add_column('proposals', sa.Column('approved_markdown', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('proposals', 'approved_markdown')
    op.drop_column('proposals', 'is_approved')
