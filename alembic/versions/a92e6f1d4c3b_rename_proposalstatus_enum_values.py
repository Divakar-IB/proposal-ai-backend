"""rename proposalstatus enum values (DRAFT->INPROGRESS, APPROVED->DONE)

Revision ID: a92e6f1d4c3b
Revises: f3a1c2d9b7e4
Create Date: 2026-07-20 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a92e6f1d4c3b'
down_revision: Union[str, Sequence[str], None] = 'f3a1c2d9b7e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE proposalstatus RENAME VALUE 'DRAFT' TO 'INPROGRESS'")
    op.execute("ALTER TYPE proposalstatus RENAME VALUE 'APPROVED' TO 'DONE'")


def downgrade() -> None:
    op.execute("ALTER TYPE proposalstatus RENAME VALUE 'INPROGRESS' TO 'DRAFT'")
    op.execute("ALTER TYPE proposalstatus RENAME VALUE 'DONE' TO 'APPROVED'")
