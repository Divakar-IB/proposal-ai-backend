"""remove APPROVED from proposalstatus enum

Revision ID: c8b3f2a1d6e9
Revises: a1b2c3d4e5f6
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c8b3f2a1d6e9'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing APPROVED proposals collapse into DONE — there's no dedicated
    # "approved" concept anymore, so DONE is the closest terminal status.
    op.execute("UPDATE proposals SET status = 'DONE' WHERE status = 'APPROVED'")

    # Postgres has no ALTER TYPE ... DROP VALUE, so the enum type is rebuilt
    # without APPROVED and the column is recast onto the new type.
    op.execute("ALTER TYPE proposalstatus RENAME TO proposalstatus_old")
    op.execute("CREATE TYPE proposalstatus AS ENUM ('INPROGRESS', 'GENERATING', 'REVIEW', 'DONE', 'FAILED')")
    op.execute(
        "ALTER TABLE proposals ALTER COLUMN status TYPE proposalstatus "
        "USING status::text::proposalstatus"
    )
    op.execute("DROP TYPE proposalstatus_old")


def downgrade() -> None:
    op.execute("ALTER TYPE proposalstatus RENAME TO proposalstatus_new")
    op.execute(
        "CREATE TYPE proposalstatus AS ENUM "
        "('INPROGRESS', 'GENERATING', 'REVIEW', 'APPROVED', 'DONE', 'FAILED')"
    )
    op.execute(
        "ALTER TABLE proposals ALTER COLUMN status TYPE proposalstatus "
        "USING status::text::proposalstatus"
    )
    op.execute("DROP TYPE proposalstatus_new")
