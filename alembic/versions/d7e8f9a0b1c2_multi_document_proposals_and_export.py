"""requirement documents belong to a proposal (many-to-one), add proposal
pdf_path, add ProposalStatus.APPROVED

Revision ID: d7e8f9a0b1c2
Revises: c1a2b3c4d5e6
Create Date: 2026-07-22 00:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'c1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requirement_documents', sa.Column('proposal_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_requirement_documents_proposal_id'), 'requirement_documents', ['proposal_id'], unique=False
    )
    op.create_foreign_key(
        'fk_requirement_documents_proposal_id', 'requirement_documents', 'proposals', ['proposal_id'], ['id']
    )

    # Backfill from the old proposals.requirement_document_id, then drop it.
    op.execute(
        """
        UPDATE requirement_documents rd
        SET proposal_id = p.id
        FROM proposals p
        WHERE p.requirement_document_id = rd.id
        """
    )

    op.drop_constraint('proposals_requirement_document_id_fkey', 'proposals', type_='foreignkey')
    op.drop_index('ix_proposals_requirement_document_id', table_name='proposals')
    op.drop_column('proposals', 'requirement_document_id')

    op.add_column('proposals', sa.Column('pdf_path', sa.Text(), nullable=True))

    # SAEnum(ProposalStatus) without values_callable stores the Python *member
    # name*, not .value — every existing label here (INPROGRESS, DONE, ...)
    # is uppercase, so the new value must match or inserts raise
    # "invalid input value for enum".
    op.execute("ALTER TYPE proposalstatus ADD VALUE IF NOT EXISTS 'APPROVED'")


def downgrade() -> None:
    op.drop_column('proposals', 'pdf_path')

    op.add_column('proposals', sa.Column('requirement_document_id', sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE proposals p
        SET requirement_document_id = rd.id
        FROM requirement_documents rd
        WHERE rd.proposal_id = p.id
        """
    )
    op.alter_column('proposals', 'requirement_document_id', nullable=False)
    op.create_index(
        op.f('ix_proposals_requirement_document_id'), 'proposals', ['requirement_document_id'], unique=False
    )
    op.create_foreign_key(
        'proposals_requirement_document_id_fkey', 'proposals', 'requirement_documents',
        ['requirement_document_id'], ['id'],
    )

    op.drop_constraint('fk_requirement_documents_proposal_id', 'requirement_documents', type_='foreignkey')
    op.drop_index(op.f('ix_requirement_documents_proposal_id'), table_name='requirement_documents')
    op.drop_column('requirement_documents', 'proposal_id')

    # Postgres cannot drop an enum value; downgrade leaves 'approved' in place.
