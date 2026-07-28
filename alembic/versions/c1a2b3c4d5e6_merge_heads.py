"""merge divergent heads

Revision ID: c1a2b3c4d5e6
Revises: b6d4e91a2f77, b71d4e2a9f6c
Create Date: 2026-07-22 00:00:00.000000

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'c1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = ('b6d4e91a2f77', 'b71d4e2a9f6c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
