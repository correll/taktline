"""Pydantic schemas for companies, memberships, and invitations."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr

Role = Literal["super_admin", "admin", "user"]


# ── Companies ──────────────────────────────────────────────────────────────────
class CompanyCreate(BaseModel):
    #: Marker from a supplier invitation link, if they arrived through one.
    #: Attribution only — it grants the inviter nothing.
    supplierInvite: Optional[str] = None
    name: str
    timezone: str = "UTC"


class CompanyPublic(BaseModel):
    id: str
    name: str
    slug: Optional[str] = None
    timezone: str = "UTC"
    role: Optional[str] = None   # the requesting user's role, when known


# ── Members ────────────────────────────────────────────────────────────────────
class MemberPublic(BaseModel):
    userId: str
    email: EmailStr
    name: Optional[str] = None
    role: str
    joinedAt: datetime


class RoleUpdate(BaseModel):
    role: Role


# ── Invitations ────────────────────────────────────────────────────────────────
class InviteCreate(BaseModel):
    email: EmailStr
    role: Role = "user"


class InvitationPublic(BaseModel):
    id: str
    email: EmailStr
    role: str
    status: str            # 'pending' | 'accepted' | 'revoked' | 'expired'
    createdAt: datetime
    expiresAt: datetime
    devLink: Optional[str] = None   # only populated on create when TAKTLINE_DEV=1


class InvitePreview(BaseModel):
    """Public preview shown on the accept-invite page (no secrets)."""
    valid: bool
    companyName: Optional[str] = None
    email: Optional[EmailStr] = None
    role: Optional[str] = None
    reason: Optional[str] = None   # why invalid, if applicable


class AcceptInviteSignup(BaseModel):
    """Create a new (auto-verified) account and accept the invite in one step."""
    password: str
    name: Optional[str] = None
