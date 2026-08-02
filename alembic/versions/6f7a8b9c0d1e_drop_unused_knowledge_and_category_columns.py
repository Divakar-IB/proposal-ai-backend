"""drop unused knowledge_documents, knowledge_chunks and proposals columns

* knowledge_documents.source_type — fully derivable from source_proposal_id
  (NULL means a manual upload, set means auto-ingested from an approved
  proposal), so it was a stored derived value. Every consumer now checks
  source_proposal_id directly: services/citation_service.py's
  proposal-content exclusion filter, and the include_generated filter in
  database/crud.py::build_knowledge_documents_query. The knowledgesourcetype
  enum type goes with it.
* knowledge_chunks.page_number — the chunk -> page mapping was a fuzzy
  substring lookup over the joined page markdown (chunking/pipeline.py's
  _locate_page) and unreliable in practice. It was written to the row and to
  Pinecone metadata but never read by any consumer — citations do not
  surface a page number.
* knowledge_chunks.embedding_version — written on ingestion, never read.
* proposals.category_ids — read during retrieval to build a Pinecone
  category filter, but no code path ever wrote it, so the filter was always
  inactive. Retrieval now queries unfiltered, which is what it already did
  at runtime.

Revision ID: 6f7a8b9c0d1e
Revises: 5e6f7a8b9c0d
Create Date: 2026-08-01 19:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6f7a8b9c0d1e'
down_revision: Union[str, Sequence[str], None] = '5e6f7a8b9c0d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('knowledge_documents', 'source_type')
    sa.Enum(name='knowledgesourcetype').drop(op.get_bind(), checkfirst=True)

    op.drop_column('knowledge_chunks', 'page_number')
    op.drop_column('knowledge_chunks', 'embedding_version')

    op.drop_column('proposals', 'category_ids')


def downgrade() -> None:
    op.add_column(
        'proposals', sa.Column('category_ids', postgresql.ARRAY(sa.Integer()), nullable=True)
    )

    op.add_column(
        'knowledge_chunks', sa.Column('embedding_version', sa.String(length=255), nullable=True)
    )
    op.add_column('knowledge_chunks', sa.Column('page_number', sa.Integer(), nullable=True))

    source_type = sa.Enum('UPLOAD', 'PROPOSAL', name='knowledgesourcetype')
    source_type.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'knowledge_documents',
        sa.Column('source_type', source_type, nullable=False, server_default='UPLOAD'),
    )
    # Restore the derived value from the column it was derivable from.
    op.execute(
        "UPDATE knowledge_documents SET source_type = 'PROPOSAL' "
        "WHERE source_proposal_id IS NOT NULL"
    )
    op.alter_column('knowledge_documents', 'source_type', server_default=None)
