"""global_settings supportedLanguages

Revision ID: a1b2c3d4e5f6
Revises: df99c7eeffd3
Create Date: 2026-08-03

Which languages a company runs in (core/languages.py). Defaults to every
language the product speaks, so existing companies change behaviour not at
all: their operators may pick any language, exactly as if the column had
always been there. Narrowing is the admin's deliberate act, never the
migration's.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'df99c7eeffd3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('global_settings', sa.Column(
        'supportedLanguages', JSONB(), nullable=False,
        server_default=sa.text('\'["en", "es", "fr-CA", "my", "ht"]\'::jsonb')))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('global_settings', 'supportedLanguages')
