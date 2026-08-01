"""merge divergent heads

Revision ID: 9f1e2d3c4b5a
Revises: c8b3f2a1d6e9, 0fbf9944ec82
Create Date: 2026-07-29 19:00:00.000000

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = '9f1e2d3c4b5a'
down_revision: Union[str, Sequence[str], None] = ('c8b3f2a1d6e9', '0fbf9944ec82')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
