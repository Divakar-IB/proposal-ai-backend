"""add source_type/source_proposal_id to knowledge_documents

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-07-29 19:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '2b3c4d5e6f7a'
down_revision: Union[str, Sequence[str], None] = '1a2b3c4d5e6f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    source_type = sa.Enum('UPLOAD', 'PROPOSAL', name='knowledgesourcetype')
    source_type.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'knowledge_documents',
        sa.Column('source_type', source_type, nullable=False, server_default='UPLOAD'),
    )
    op.alter_column('knowledge_documents', 'source_type', server_default=None)

    op.add_column(
        'knowledge_documents', sa.Column('source_proposal_id', sa.Integer(), nullable=True)
    )
    op.create_unique_constraint(
        'uq_knowledge_documents_source_proposal_id', 'knowledge_documents', ['source_proposal_id']
    )
    op.create_foreign_key(
        'fk_knowledge_documents_source_proposal_id',
        'knowledge_documents', 'proposals', ['source_proposal_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_knowledge_documents_source_proposal_id', 'knowledge_documents', type_='foreignkey'
    )
    op.drop_constraint(
        'uq_knowledge_documents_source_proposal_id', 'knowledge_documents', type_='unique'
    )
    op.drop_column('knowledge_documents', 'source_proposal_id')
    op.drop_column('knowledge_documents', 'source_type')
    sa.Enum(name='knowledgesourcetype').drop(op.get_bind(), checkfirst=True)
