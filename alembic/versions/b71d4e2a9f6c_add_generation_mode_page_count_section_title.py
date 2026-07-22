"""add generation_mode/page_count to proposals, title to proposal_sections

Revision ID: b71d4e2a9f6c
Revises: a92e6f1d4c3b
Create Date: 2026-07-21 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b71d4e2a9f6c'
down_revision: Union[str, Sequence[str], None] = 'a92e6f1d4c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    generation_mode = sa.Enum('LLM_ONLY', 'KNOWLEDGE_AUGMENTED', name='generationmode')
    generation_mode.create(op.get_bind(), checkfirst=True)

    op.add_column('proposals', sa.Column('generation_mode', generation_mode, nullable=True))
    op.add_column('proposals', sa.Column('page_count', sa.Integer(), nullable=True))
    op.add_column('proposal_sections', sa.Column('title', sa.String(length=255), nullable=False, server_default=''))
    op.alter_column('proposal_sections', 'title', server_default=None)


def downgrade() -> None:
    op.drop_column('proposal_sections', 'title')
    op.drop_column('proposals', 'page_count')
    op.drop_column('proposals', 'generation_mode')
    sa.Enum(name='generationmode').drop(op.get_bind(), checkfirst=True)
