"""workHours 0/1 to quarter scale 0-4

Revision ID: a11112416993
Revises: 37e34c7d7187
Create Date: 2026-07-26 12:45:02.460619

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'a11112416993'
down_revision: Union[str, Sequence[str], None] = '37e34c7d7187'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rescale existing 0/1 workHours to the 0–4 quarter scale (open hour → 4)."""
    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id, "workHours" FROM global_settings')).fetchall()
    for rid, wh in rows:
        if not wh:
            continue
        rescaled = [[4 if c else 0 for c in row] for row in wh]   # 0/1 → 0/4
        conn.execute(
            sa.text('UPDATE global_settings SET "workHours" = :wh WHERE id = :id').bindparams(
                sa.bindparam('wh', json.dumps(rescaled), type_=JSONB()),
                sa.bindparam('id', rid),
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id, "workHours" FROM global_settings')).fetchall()
    for rid, wh in rows:
        if not wh:
            continue
        collapsed = [[1 if c else 0 for c in row] for row in wh]   # 0–4 → 0/1
        conn.execute(
            sa.text('UPDATE global_settings SET "workHours" = :wh WHERE id = :id').bindparams(
                sa.bindparam('wh', json.dumps(collapsed), type_=JSONB()),
                sa.bindparam('id', rid),
            )
        )
