"""add capability_tags, section confidence/review fields, proposal category_ids

Revision ID: b6d4e91a2f77
Revises: a92e6f1d4c3b
Create Date: 2026-07-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b6d4e91a2f77'
down_revision: Union[str, Sequence[str], None] = 'a92e6f1d4c3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requirement_documents', sa.Column('capability_tags', postgresql.JSONB(), nullable=True))
    op.add_column('proposal_sections', sa.Column('confidence_score', sa.Float(), nullable=True))
    op.add_column(
        'proposal_sections',
        sa.Column('review_flag', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('proposals', sa.Column('category_ids', postgresql.ARRAY(sa.Integer()), nullable=True))


def downgrade() -> None:
    op.drop_column('proposals', 'category_ids')
    op.drop_column('proposal_sections', 'review_flag')
    op.drop_column('proposal_sections', 'confidence_score')
    op.drop_column('requirement_documents', 'capability_tags')
