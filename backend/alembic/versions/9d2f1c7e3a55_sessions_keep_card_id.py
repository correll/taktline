"""sessions keep their card id after the card is gone

Revision ID: 9d2f1c7e3a55
Revises: 7c1e2a9d4b10
Create Date: 2026-10-22 22:30:00

"""
from typing import Sequence, Union

from alembic import op


revision: str = '9d2f1c7e3a55'
down_revision: Union[str, Sequence[str], None] = '7c1e2a9d4b10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('sessions_cardId_fkey', 'sessions', type_='foreignkey')


def downgrade() -> None:
    op.execute('UPDATE sessions SET "cardId" = NULL '
               'WHERE "cardId" IS NOT NULL AND "cardId" NOT IN (SELECT id FROM cards)')
    op.create_foreign_key('sessions_cardId_fkey', 'sessions', 'cards', ['cardId'], ['id'],
                          ondelete='SET NULL')
