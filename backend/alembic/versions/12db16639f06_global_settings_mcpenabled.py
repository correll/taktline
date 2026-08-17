"""global_settings mcpEnabled

Whether this company answers MCP calls from AI agents (app/routers/mcp.py).
Defaults to false, so every existing company stays switched off until someone
deliberately turns it on — a feature that opens a door has to be opt-in for
accounts that were never asked.

The autogenerate run also proposed a `ck_user_platform_role` check constraint,
which is unrelated pre-existing drift between the ORM and this database. It is
deliberately not carried here: a migration should do the one thing its name
says, or the next person bisecting a schema problem cannot trust any of them.

Revision ID: 12db16639f06
Revises: a1b2c3d4e5f6
Create Date: 2026-08-16 16:49:50.669404

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12db16639f06'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('global_settings',
                  sa.Column('mcpEnabled', sa.Boolean(),
                            server_default=sa.text('false'), nullable=False))


def downgrade() -> None:
    op.drop_column('global_settings', 'mcpEnabled')
