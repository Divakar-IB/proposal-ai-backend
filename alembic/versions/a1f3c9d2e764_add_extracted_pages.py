"""add extracted_pages

Revision ID: a1f3c9d2e764
Revises: 872db9f9115a
Create Date: 2026-07-19 17:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d2e764'
down_revision: Union[str, Sequence[str], None] = '872db9f9115a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'knowledge_documents',
        sa.Column('extracted_pages', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        'requirement_documents',
        sa.Column('extracted_pages', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('requirement_documents', 'extracted_pages')
    op.drop_column('knowledge_documents', 'extracted_pages')
