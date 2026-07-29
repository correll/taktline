"""station branchMode split-or-choice

Revision ID: b2f80d53d0de
Revises: f914f862d184
Create Date: 2026-07-29 11:04:29.566094

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2f80d53d0de'
down_revision: Union[str, Sequence[str], None] = 'f914f862d184'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('stations', sa.Column('branchMode', sa.String(), nullable=True))
    op.create_check_constraint(
        'ck_station_branch_mode', 'stations',
        '"branchMode" IS NULL OR "branchMode" IN (\'split\', \'choice\')',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_station_branch_mode', 'stations', type_='check')
    op.drop_column('stations', 'branchMode')
