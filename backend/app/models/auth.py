"""Pydantic schemas for authentication and the /auth/me payload."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, field_validator

from ..core.config import settings


def _validate_password(v: str) -> str:
    if len(v) < settings.password_min_length:
        raise ValueError(f"password must be at least {settings.password_min_length} characters")
    return v


# ── Request bodies ─────────────────────────────────────────────────────────────
class SignupBody(BaseModel):
    email: EmailStr
    password: str
    name: Optional[str] = None
    #: BCP 47 code from core/languages.py. A new account may pick any language
    #: the product speaks; invited operators are constrained by their company.
    language: Optional[str] = None
    # Carry the line built in the sandbox over to the new account. Authorised by
    # the sandbox session cookie the browser already holds — no code to copy.
    adoptSandbox: bool = False
    companyName: Optional[str] = None   # rename the adopted company
    # Which version of the end-user agreement the signup screen displayed and
    # the person accepted. Recorded on the user so "they agreed" can later be
    # answered with "to this text, on this date".
    acceptedTermsVersion: Optional[str] = None
    #: Carried from a supplier invitation email so the customer who sent it gets
    #: credited when their supplier actually joins. See `routers/network.py`.
    supplierInvite: Optional[str] = None

    _pw = field_validator("password")(_validate_password)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class VerifyEmailBody(BaseModel):
    token: str


class ResendVerificationBody(BaseModel):
    email: EmailStr


class ForgotPasswordBody(BaseModel):
    email: EmailStr


class ResetPasswordBody(BaseModel):
    token: str
    newPassword: str

    _pw = field_validator("newPassword")(_validate_password)


# ── Responses ──────────────────────────────────────────────────────────────────
class UserPublic(BaseModel):
    id: str
    email: EmailStr
    emailVerified: bool
    name: Optional[str] = None
    preferences: dict = {}
    platformRole: Optional[str] = None   # 'owner' | 'support' | None (customer service)
    isSandbox: bool = False              # anonymous try-it account (restricted)


class PreferencesPatch(BaseModel):
    """Partial update of the user's cross-device preferences. Only known keys
    are accepted so the blob can't grow arbitrarily."""
    theme: Optional[str] = None
    language: Optional[str] = None

    @field_validator("language")
    @classmethod
    def _language_valid(cls, v: Optional[str]) -> Optional[str]:
        from ..core import languages
        if v is not None and not languages.valid(v):
            raise ValueError(f"unknown language '{v}'")
        return v

    @field_validator("theme")
    @classmethod
    def _theme_valid(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("day", "night"):
            raise ValueError("theme must be 'day' or 'night'")
        return v


class CompanyMembership(BaseModel):
    """A company the current user belongs to, plus their role in it. Platform
    staff also see companies they're impersonating (impersonated=True, with the
    grant's expiry) so the whole frontend works unchanged during support."""
    id: str
    name: str
    slug: Optional[str] = None
    role: str
    timezone: str = "UTC"
    impersonated: bool = False
    impersonationExpiresAt: Optional[datetime] = None
    #: Billing state, so the app knows on its first request which tenants are
    #: on trial, over their limit, or locked. Without it the company switcher
    #: cannot mark a locked tenant and a 402 has no company to route to.
    plan: str = "trial"
    planLabel: str = "Trial"
    planState: str = "ok"          # ok | read_only | locked
    stationLimit: Optional[int] = None
    integrations: bool = False


class MeResponse(BaseModel):
    user: UserPublic
    companies: List[CompanyMembership]


class MessageResponse(BaseModel):
    """Generic acknowledgement. `devLink` is only populated when TAKTLINE_DEV=1."""
    message: str
    devLink: Optional[str] = None
