"""global settings carry the plant's breaks

Revision ID: b4e8a2c61f07
Revises: 9d2f1c7e3a55
Create Date: 2026-10-23 23:30:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'b4e8a2c61f07'
down_revision: Union[str, Sequence[str], None] = '9d2f1c7e3a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('global_settings', sa.Column(
        'breaks', postgresql.JSONB(astext_type=sa.Text()), nullable=False,
        server_default=sa.text("'[]'::jsonb")))


def downgrade() -> None:
    op.drop_column('global_settings', 'breaks')
