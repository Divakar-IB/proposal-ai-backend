"""add content_format/structured_content to proposal_sections

Revision ID: 1a2b3c4d5e6f
Revises: 9f1e2d3c4b5a
Create Date: 2026-07-29 19:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1a2b3c4d5e6f'
down_revision: Union[str, Sequence[str], None] = '9f1e2d3c4b5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    content_format = sa.Enum('MARKDOWN', 'STRUCTURED', name='sectioncontentformat')
    content_format.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'proposal_sections',
        sa.Column(
            'content_format', content_format, nullable=False, server_default='MARKDOWN'
        ),
    )
    op.alter_column('proposal_sections', 'content_format', server_default=None)
    op.add_column(
        'proposal_sections', sa.Column('structured_content', postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('proposal_sections', 'structured_content')
    op.drop_column('proposal_sections', 'content_format')
    sa.Enum(name='sectioncontentformat').drop(op.get_bind(), checkfirst=True)
