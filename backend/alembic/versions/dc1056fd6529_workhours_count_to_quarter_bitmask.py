"""workHours count to quarter bitmask

Revision ID: dc1056fd6529
Revises: a11112416993
Create Date: 2026-07-26 13:10:55.737862

Rescales workHours cells from a 0–4 "open quarter count" (interpreted as the
*last* N quarters of the hour) to a 4-bit quarter mask, so an hour can also be
open for its *first* N quarters (shift ends early). See core.schedule.

  count → mask (last N quarters set):  0→0  1→0b1000(8)  2→0b1100(12)  3→0b1110(14)  4→0b1111(15)
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision: str = 'dc1056fd6529'
down_revision: Union[str, Sequence[str], None] = 'a11112416993'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _count_to_mask(c: int) -> int:
    c = max(0, min(4, int(c)))
    # open the last c quarters: bits (4-c)..3
    return ((1 << c) - 1) << (4 - c) if c else 0


def _mask_to_count(m: int) -> int:
    m = max(0, min(15, int(m)))
    return bin(m).count("1")


def _remap(fn) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text('SELECT id, "workHours" FROM global_settings')).fetchall()
    for rid, wh in rows:
        if not wh:
            continue
        if isinstance(wh, str):
            wh = json.loads(wh)
        remapped = [[fn(c) for c in row] for row in wh]
        conn.execute(
            sa.text('UPDATE global_settings SET "workHours" = :wh WHERE id = :id').bindparams(
                sa.bindparam('wh', json.dumps(remapped), type_=JSONB()),
                sa.bindparam('id', rid),
            )
        )


def upgrade() -> None:
    _remap(_count_to_mask)


def downgrade() -> None:
    # Lossy: collapse a mask back to a plain open-quarter count (position is lost).
    _remap(_mask_to_count)
