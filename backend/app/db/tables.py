"""SQLAlchemy ORM table definitions.

Design notes
------------
* **UUID primary keys** (generated app-side via ``uuid.uuid4``) serialised to
  the API as opaque ``_id`` strings — the frontend never inspects their shape.
* **Foreign keys** enforce referential integrity that the Mongo version only
  hoped for. ``ON DELETE CASCADE`` where the child cannot outlive the parent,
  ``SET NULL`` for optional links.
* **CHECK constraints** move domain invariants (``quantity >= 1``, no self-loop,
  status/unit enumerations) into the database.
* **JSONB** for genuinely document-shaped fields: station ``position``, card
  ``bins``/``fields``, ``adapterConfig``, lot-template ``fields`` and the
  denormalised ``process.routes`` list.
* **TIMESTAMP WITH TIME ZONE** columns — asyncpg returns tz-aware datetimes, so
  the naive-datetime normalisation dance the Mongo code needed is gone.

``card_events`` deliberately keeps ``cardId`` as a plain indexed string with no
FK: it is an append-only audit log that must retain the ``'deleted'`` event
recorded *after* a card is removed.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .connection import Base
from ..models.common import utcnow
from ..core.schedule import default_work_hours as _default_work_hours


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def _company_fk() -> Mapped[uuid.UUID]:
    """Tenant scope: every domain row belongs to exactly one company."""
    return mapped_column(
        UUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


# ─── Identity / tenancy ────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("\"platformRole\" IN ('support')", name="ck_user_platform_role"),
    )

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)  # stored lowercased
    passwordHash: Mapped[str] = mapped_column(String, nullable=False)
    emailVerified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    # Cross-device personal settings (e.g. {"theme": "day"}) — account-scoped,
    # not company-scoped.
    preferences: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    # Instance-level customer-service tier ('support'), granted only by a
    # platform owner (PLATFORM_OWNER_EMAILS). NULL for everyone else. Owners
    # are defined by the env allowlist, never by a DB value — no API can mint one.
    platformRole: Mapped[str | None] = mapped_column(String, nullable=True)
    # Anonymous try-it accounts from the landing page. Permanently restricted:
    # no floor-plan uploads, invitations, API keys, orders, or extra companies.
    isSandbox: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false"))
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("role IN ('super_admin', 'admin', 'user')", name="ck_membership_role"),
        UniqueConstraint("companyId", "userId", name="uq_membership_user_company"),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    createdAt: Mapped[datetime] = _created()


class Invitation(Base):
    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("role IN ('super_admin', 'admin', 'user')", name="ck_invitation_role"),
        # At most one live (not accepted, not revoked) invite per email per company.
        Index(
            "uq_invitation_pending", "companyId", "email", unique=True,
            postgresql_where=text('"acceptedAt" IS NULL AND "revokedAt" IS NULL'),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(String, nullable=False)  # stored lowercased
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    tokenHash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    invitedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acceptedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = _created()


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[uuid.UUID] = _pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    tokenHash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    csrfToken: Mapped[str] = mapped_column(String, nullable=False)
    createdAt: Mapped[datetime] = _created()
    lastSeenAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    userAgent: Mapped[str | None] = mapped_column(String, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)


class AuthToken(Base):
    """Single-use email-verification and password-reset tokens (hashed at rest)."""
    __tablename__ = "auth_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('email_verify', 'password_reset')", name="ck_auth_token_purpose"
        ),
        Index("ix_auth_tokens_user_purpose", "userId", "purpose"),
    )

    id: Mapped[uuid.UUID] = _pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    tokenHash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[datetime] = _created()


class Station(Base):
    __tablename__ = "stations"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    position: Mapped[dict] = mapped_column(
        JSONB, nullable=False,
        default=lambda: {"x": 0.0, "y": 0.0, "width": 60.0, "height": 60.0},
    )
    adapterType: Mapped[str | None] = mapped_column(String, nullable=True)
    adapterConfig: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    icon: Mapped[str | None] = mapped_column(String, nullable=True)
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class StationFavorite(Base):
    """A user's favorite locations — surfaced first in the operator picker.
    Per user (not per membership): the station's companyId already scopes it."""
    __tablename__ = "station_favorites"

    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="CASCADE"),
        primary_key=True, index=True,
    )
    createdAt: Mapped[datetime] = _created()


class SupportGrant(Base):
    """A time-boxed customer-service impersonation grant: while active
    (not ended, not expired) the staff user acts as super_admin of the company.
    Always explicit, always audited, always visible in the UI."""
    __tablename__ = "support_grants"

    id: Mapped[uuid.UUID] = _pk()
    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    createdAt: Mapped[datetime] = _created()
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UploadedImage(Base):
    """Floor-plan images, stored in Postgres so ephemeral hosting (free-tier
    PaaS with no persistent disk) survives redeploys. The /uploads endpoint
    serves them through a disk read-through cache, so the bytes leave the
    database once per instance, not once per request."""
    __tablename__ = "uploaded_images"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    filename: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    contentType: Mapped[str] = mapped_column(String, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    createdAt: Mapped[datetime] = _created()


class UsageCounter(Base):
    """Per-company, per-calendar-month usage totals for the platform dashboard.
    Incremented in memory on the request path and flushed periodically (see
    core/usage.py) — one row per (company, month)."""
    __tablename__ = "usage_counters"

    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        primary_key=True,
    )
    month: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    apiRequests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    wsMessages: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PlatformAudit(Base):
    """Audit trail for every platform-staff action (impersonation start/end,
    deletes, role grants). No FKs — audit rows must survive the deletion of
    both the actor and the target (same rationale as card_events)."""
    __tablename__ = "platform_audit"

    id: Mapped[uuid.UUID] = _pk()
    actorUserId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actorEmail: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    targetType: Mapped[str | None] = mapped_column(String, nullable=True)
    targetId: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    createdAt: Mapped[datetime] = _created()


class Process(Base):
    __tablename__ = "processes"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    routes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    mapId: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class Route(Base):
    __tablename__ = "routes"
    __table_args__ = (
        CheckConstraint("quantity >= 1", name="ck_route_quantity_positive"),
        CheckConstraint("load <> unload", name="ck_route_no_self_loop"),
        UniqueConstraint("processId", "load", "unload", name="uq_route_edge"),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    processId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    load: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="CASCADE"),
        nullable=False,
    )
    unload: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="CASCADE"),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class LotTemplate(Base):
    __tablename__ = "lot_templates"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    processId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processes.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    startStationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    fields: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    color: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        CheckConstraint('"totalQuantity" >= 1', name="ck_card_total_positive"),
        CheckConstraint(
            "status IN ('idle', 'working', 'done')", name="ck_card_status"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    lotTemplateId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("lot_templates.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    processId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processes.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Human lot code (e.g. "E4096A") — user-defined at creation or generated;
    # inherited by the pieces when a lot is split apart (unmerge).
    lotNum: Mapped[str | None] = mapped_column(String, nullable=True)
    totalQuantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    bins: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fields: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    status: Mapped[str] = mapped_column(String, nullable=False, default="idle")
    # Set when this lot was released by a production order (survives merges via
    # propagation). SET NULL so deleting an order doesn't delete its lots.
    orderId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("production_orders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class CardEvent(Base):
    __tablename__ = "card_events"
    __table_args__ = (
        CheckConstraint(
            "type IN ('created', 'moved', 'flagged', 'unflagged', 'updated', 'deleted')",
            name="ck_card_event_type",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    # Plain string, no FK: audit rows must survive their card's deletion.
    cardId: Mapped[str] = mapped_column(String, nullable=False, index=True)
    type: Mapped[str] = mapped_column(String, nullable=False)
    fromStation: Mapped[str | None] = mapped_column(String, nullable=True)
    toStation: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str] = mapped_column(String, nullable=False, default="")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class WorkSession(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_session_quantity_non_negative"),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    stationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("stations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    cardId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cards.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    operatorId: Mapped[str] = mapped_column(String, nullable=False, default="default")
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    startedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    endedAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    durationSec: Mapped[float | None] = mapped_column(Float, nullable=True)


class MapSettings(Base):
    __tablename__ = "map_settings"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    floorPlanUrl: Mapped[str | None] = mapped_column(String, nullable=True)
    pixelsPerUnit: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    unit: Mapped[str] = mapped_column(
        String, nullable=False, default="ft",
    )
    stationSizeUnits: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    mapWidthPx: Mapped[float | None] = mapped_column(Float, nullable=True)
    mapHeightPx: Mapped[float | None] = mapped_column(Float, nullable=True)
    updatedAt: Mapped[datetime] = _updated()

    __table_args__ = (
        CheckConstraint("unit IN ('ft', 'm')", name="ck_map_unit"),
    )


class GlobalSettings(Base):
    __tablename__ = "global_settings"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    timezone: Mapped[str] = mapped_column(String, nullable=False, default="UTC")
    # 7×24 grid of 0/1 (day 0 = Monday) — the hours the plant is meant to run.
    # Drives OEE (working time ÷ open time). Defaults to Mon–Fri 9–5.
    workHours: Mapped[list] = mapped_column(JSONB, nullable=False, default=_default_work_hours)


# ─── ERP / production orders ────────────────────────────────────────────────────

class ProductionOrder(Base):
    """A release of N units of a product onto the floor, optionally originating
    from an external ERP order. Anchors idempotency and completion reporting."""
    __tablename__ = "production_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','released','in_progress','completed','cancelled')",
            name="ck_order_status",
        ),
        CheckConstraint("quantity >= 1", name="ck_order_quantity_positive"),
        # Idempotency: one order per external reference per source per company.
        UniqueConstraint("companyId", "source", "externalRef", name="uq_order_external_ref"),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    source: Mapped[str] = mapped_column(String, nullable=False, default="manual")   # manual|odoo|netsuite
    externalRef: Mapped[str | None] = mapped_column(String, nullable=True)          # ERP order id
    productTemplateId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_templates.id", ondelete="SET NULL"), nullable=True,
    )
    mergeStationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stations.id", ondelete="SET NULL"), nullable=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantityDone: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    note: Mapped[str] = mapped_column(String, nullable=False, default="")
    createdAt: Mapped[datetime] = _created()
    updatedAt: Mapped[datetime] = _updated()


class IntegrationOutbox(Base):
    """Durable, at-least-once event log for external (ERP) delivery. Written in
    the same transaction as the state change; a connector polls pending rows,
    delivers to the ERP, then acks them."""
    __tablename__ = "integration_outbox"
    __table_args__ = (
        CheckConstraint("status IN ('pending','delivered','failed')", name="ck_outbox_status"),
        Index("ix_outbox_company_status", "companyId", "status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    orderId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("production_orders.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    eventType: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    createdAt: Mapped[datetime] = _created()
    deliveredAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKey(Base):
    """A scoped, revocable service credential for external integrations
    (connectors, Zapier, a customer's IT). Only the SHA-256 hash is stored."""
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = _pk()
    companyId: Mapped[uuid.UUID] = _company_fk()
    name: Mapped[str] = mapped_column(String, nullable=False)
    prefix: Mapped[str] = mapped_column(String, nullable=False)        # display only, e.g. tk_ab12cd34
    keyHash: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    createdAt: Mapped[datetime] = _created()
    lastUsedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
