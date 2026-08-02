"""drop unused proposal and proposal_section columns

Removes columns that no live code path ever writes:

* proposals.is_approved / approved_markdown — the whole-proposal approval
  feature was removed in c8b3f2a1d6e9 (drop of ProposalStatus.APPROVED);
  these were left behind.
* proposals.proposal_json — export builds this shape on the fly
  (services/proposal_export_service.py::_build_proposal_json), it was never
  snapshotted to the row.
* proposals.docx_path / pdf_path — export returns rendered bytes in the
  response and never persists a file to S3.
* proposal_sections.retry_count / confidence_score / review_flag — only ever
  written by proposal_review_service.regenerate_section/approve_section,
  which had no router endpoint and are removed in the same change.
* proposal_sections.content_format / structured_content — added in
  1a2b3c4d5e6f for structured (pricing/milestone) sections that were never
  built; nothing read or wrote them. The sectioncontentformat enum type goes
  with them.

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-08-01 19:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5e6f7a8b9c0d'
down_revision: Union[str, Sequence[str], None] = '4d5e6f7a8b9c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('proposals', 'is_approved')
    op.drop_column('proposals', 'approved_markdown')
    op.drop_column('proposals', 'proposal_json')
    op.drop_column('proposals', 'docx_path')
    op.drop_column('proposals', 'pdf_path')

    op.drop_column('proposal_sections', 'retry_count')
    op.drop_column('proposal_sections', 'confidence_score')
    op.drop_column('proposal_sections', 'review_flag')
    op.drop_column('proposal_sections', 'structured_content')
    op.drop_column('proposal_sections', 'content_format')

    sa.Enum(name='sectioncontentformat').drop(op.get_bind(), checkfirst=True)


def downgrade() -> None:
    content_format = sa.Enum('MARKDOWN', 'STRUCTURED', name='sectioncontentformat')
    content_format.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'proposal_sections',
        sa.Column('content_format', content_format, nullable=False, server_default='MARKDOWN'),
    )
    op.alter_column('proposal_sections', 'content_format', server_default=None)
    op.add_column(
        'proposal_sections', sa.Column('structured_content', postgresql.JSONB(), nullable=True)
    )
    op.add_column(
        'proposal_sections',
        sa.Column('review_flag', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('proposal_sections', 'review_flag', server_default=None)
    op.add_column('proposal_sections', sa.Column('confidence_score', sa.Float(), nullable=True))
    op.add_column(
        'proposal_sections',
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.alter_column('proposal_sections', 'retry_count', server_default=None)

    op.add_column('proposals', sa.Column('pdf_path', sa.Text(), nullable=True))
    op.add_column('proposals', sa.Column('docx_path', sa.Text(), nullable=True))
    op.add_column(
        'proposals', sa.Column('proposal_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    op.add_column('proposals', sa.Column('approved_markdown', sa.Text(), nullable=True))
    op.add_column(
        'proposals',
        sa.Column('is_approved', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('proposals', 'is_approved', server_default=None)
