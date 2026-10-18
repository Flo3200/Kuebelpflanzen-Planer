"""Platform level: agent tokens and their call log, human confirmations, invoices, platform counters."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, OptionalTenantMixin, TimestampMixin


class AgentToken(IdMixin, OptionalTenantMixin, Base):
    """API token of an enrolled agent. tenant_id NULL = admin agent (platform)."""

    __tablename__ = "agent_tokens"
    __rls__ = "strict"

    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="tenant")  # tenant | admin
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    prefix: Mapped[str] = mapped_column(String(12))
    scopes: Mapped[list[Any]] = mapped_column(default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calls: Mapped[int] = mapped_column(Integer, default=0)
    rate_per_min: Mapped[int | None] = mapped_column(Integer)
    enrolled_ip: Mapped[str | None] = mapped_column(String(64))
    enrolled_agent: Mapped[str | None] = mapped_column(String(300))


class AgentCall(IdMixin, OptionalTenantMixin, Base):
    """Every API call of an agent (method, path, status, duration)."""

    __tablename__ = "agent_calls"
    __rls__ = "strict"

    token_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_tokens.id", ondelete="CASCADE"), index=True
    )
    method: Mapped[str] = mapped_column(String(8))
    path: Mapped[str] = mapped_column(String(300))
    status: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    acting_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class PendingConfirmation(IdMixin, OptionalTenantMixin, Base):
    """A destructive or billing-relevant agent action waiting for a human.

    The agent repeats its request with the header X-KP-Confirmation: <id> once a human approved it.
    """

    __tablename__ = "pending_confirmations"
    __rls__ = "strict"

    token_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("agent_tokens.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    method: Mapped[str | None] = mapped_column(String(8))
    path: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(
        String(12), default="pending"
    )  # pending | approved | rejected | used | expired
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class Invoice(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    """An invoice as issued (amounts frozen).

    kind 'platform': the platform operator bills a tenant (tenant_id = recipient).
    kind 'customer': a tenant bills its own customer for an order (tenant_id = issuer).
    The payment fields leave room for online payment later (e.g. Stripe Connect).
    """

    __tablename__ = "invoices"
    __rls__ = "strict"

    kind: Mapped[str] = mapped_column(String(10), default="platform")
    number: Mapped[str] = mapped_column(String(40), index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("pickup_orders.id", ondelete="SET NULL")
    )
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    issuer: Mapped[dict[str, Any]] = mapped_column(default=dict)
    recipient: Mapped[dict[str, Any]] = mapped_column(default=dict)
    lines: Mapped[list[Any]] = mapped_column(default=list)
    net_eur: Mapped[float] = mapped_column(Float, default=0)
    vat_pct: Mapped[float] = mapped_column(Float, default=0)
    vat_eur: Mapped[float] = mapped_column(Float, default=0)
    gross_eur: Mapped[float] = mapped_column(Float, default=0)
    small_business: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(12), default="issued")  # issued | paid | cancelled
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payment_provider: Mapped[str | None] = mapped_column(String(30))
    payment_ref: Mapped[str | None] = mapped_column(String(120))
    cancels_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class PlatformCounter(Base):
    """Gap-free numbers of the platform operator (invoice numbers)."""

    __tablename__ = "platform_counters"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)
