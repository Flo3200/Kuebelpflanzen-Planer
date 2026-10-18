"""Platform core: tenants, users, sessions, settings values, audit log, jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, OptionalTenantMixin, SoftDeleteMixin, TimestampMixin


class Tenant(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    """A nursery (Gärtnerei). The tenants table itself is filtered by id, see migration."""

    __tablename__ = "tenants"
    __rls__ = "self"

    name: Mapped[str] = mapped_column(String(200), info={"group": "master", "required": True})
    slug: Mapped[str] = mapped_column(String(80), unique=True, info={"group": "master", "optional": True})
    legal_name: Mapped[str | None] = mapped_column(String(300), info={"advanced": True, "group": "master"})
    street: Mapped[str | None] = mapped_column(String(200), info={"group": "address"})
    postal_code: Mapped[str | None] = mapped_column(String(20), info={"group": "address"})
    city: Mapped[str | None] = mapped_column(String(120), info={"group": "address"})
    country: Mapped[str] = mapped_column(String(2), default="DE", info={"advanced": True, "group": "address"})
    depot_lat: Mapped[float | None] = mapped_column(Float, info={"group": "address", "unit": "°"})
    depot_lon: Mapped[float | None] = mapped_column(Float, info={"group": "address", "unit": "°"})
    email: Mapped[str | None] = mapped_column(String(200), info={"advanced": True, "group": "contact"})
    phone: Mapped[str | None] = mapped_column(String(60), info={"advanced": True, "group": "contact"})
    vat_id: Mapped[str | None] = mapped_column(
        String(40), info={"module": "customer_billing", "group": "billing"}
    )
    tax_number: Mapped[str | None] = mapped_column(
        String(40), info={"module": "customer_billing", "group": "billing"}
    )
    iban: Mapped[str | None] = mapped_column(
        String(40), info={"module": "customer_billing", "group": "billing"}
    )
    status: Mapped[str] = mapped_column(
        String(20), default="active", info={"group": "master", "enum": ["active", "suspended"]}
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, info={"group": "master"})
    current_season: Mapped[int | None] = mapped_column(Integer, info={"advanced": True, "group": "master"})


ROLES = ("admin", "owner", "dispatcher", "driver", "customer", "agent")


class User(IdMixin, TimestampMixin, SoftDeleteMixin, OptionalTenantMixin, Base):
    """Login account. tenant_id NULL = platform admin."""

    __tablename__ = "users"
    __rls__ = "strict"

    email: Mapped[str | None] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))
    password_hash: Mapped[str | None] = mapped_column(String(300))
    extra_permissions: Mapped[list[Any]] = mapped_column(default=list)
    revoked_permissions: Mapped[list[Any]] = mapped_column(default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    staff_member_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # role customer: own data only
    pin_hash: Mapped[str | None] = mapped_column(String(300))
    pin_lookup: Mapped[str | None] = mapped_column(String(64), index=True)
    language: Mapped[str] = mapped_column(String(5), default="de")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(IdMixin, Base):
    """Server-side login session. Only the SHA-256 of the token is stored."""

    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    acting_tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(20), default="web")
    csrf_token: Mapped[str] = mapped_column(String(64))
    mfa_pending: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))


class LoginAttempt(IdMixin, Base):
    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_login_attempts_key_time", "key", "created_at"),)

    key: Mapped[str] = mapped_column(String(300))
    success: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OneTimeCode(IdMixin, OptionalTenantMixin, Base):
    """Single-use codes: driver login links, agent enrolment links, password resets."""

    __tablename__ = "one_time_codes"
    __rls__ = "strict"

    purpose: Mapped[str] = mapped_column(String(30))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reusable: Mapped[bool] = mapped_column(Boolean, default=False)


class SettingValue(IdMixin, OptionalTenantMixin, Base):
    """One override of a registry setting on one level.

    scope: 'platform' (tenant_id NULL), 'tenant', or an object kind ('staff', 'vehicle', ...)
    """

    __tablename__ = "setting_values"
    __table_args__ = (
        UniqueConstraint("scope", "tenant_id", "object_id", "key", postgresql_nulls_not_distinct=True),
    )

    scope: Mapped[str] = mapped_column(String(30))
    object_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(IdMixin, Base):
    """Every change: who, when, old/new value, channel. Supports undo."""

    __tablename__ = "audit_log"
    __rls__ = "strict"
    __table_args__ = (Index("ix_audit_log_tenant_time", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_label: Mapped[str | None] = mapped_column(String(200))
    via: Mapped[str] = mapped_column(String(20))  # ui | settings_ai | agent | api | system
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(30))
    old_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    undoable: Mapped[bool] = mapped_column(Boolean, default=False)
    undone_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Job(IdMixin, Base):
    """Background job, claimed by the worker with SELECT ... FOR UPDATE SKIP LOCKED."""

    __tablename__ = "jobs"
    __rls__ = "strict"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
