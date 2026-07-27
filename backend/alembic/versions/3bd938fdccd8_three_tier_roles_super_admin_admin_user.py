"""three-tier roles: super_admin admin user

Revision ID: 3bd938fdccd8
Revises: f66922532bca
Create Date: 2026-07-26 15:12:50.218754

Introduces a middle role. The old two roles are renamed so the new one can sit
between them:

    admin  → super_admin   (full config + member management, unchanged powers)
    member → user          (operator)
    admin  (new)           — user + create lots, pull precursors, release orders

Renames the stored values on memberships + invitations and swaps the CHECK
constraints. No existing user's effective privileges change (the top tier keeps
everything as super_admin); the new middle tier is only reachable by assignment.
"""
from typing import Sequence, Union

from alembic import op


revision: str = '3bd938fdccd8'
down_revision: Union[str, Sequence[str], None] = 'f66922532bca'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ("memberships", "invitations")
CK = {"memberships": "ck_membership_role", "invitations": "ck_invitation_role"}


def upgrade() -> None:
    for t in TABLES:
        op.drop_constraint(CK[t], t, type_="check")
        # Rename existing values (old 'admin' first, before the new value exists).
        op.execute(f"UPDATE {t} SET role = 'super_admin' WHERE role = 'admin'")
        op.execute(f"UPDATE {t} SET role = 'user' WHERE role = 'member'")
        op.create_check_constraint(CK[t], t, "role IN ('super_admin', 'admin', 'user')")


def downgrade() -> None:
    for t in TABLES:
        op.drop_constraint(CK[t], t, type_="check")
        # Collapse back to two tiers: the middle 'admin' folds down to 'member'.
        op.execute(f"UPDATE {t} SET role = 'member' WHERE role IN ('user', 'admin')")
        op.execute(f"UPDATE {t} SET role = 'admin' WHERE role = 'super_admin'")
        op.create_check_constraint(CK[t], t, "role IN ('admin', 'member')")
