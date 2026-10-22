"""Notifications for the office (bell in the top bar) and customer share links (photos, location)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, TenantMixin, TimestampMixin

NOTIFICATION_KINDS = [
    "photos_missing",  # a draft lacks photos or details; message to the customer is ready
    "customer_upload",  # the customer sent photos or the location through the share link
    "tour_aborted",  # a driver ended a tour early, open stops went back to planning
    "team_created",  # a spontaneous team was created by message or voice
    "info",
]


class Notification(IdMixin, TimestampMixin, TenantMixin, Base):
    """Something the office should look at. ``message`` is a ready text for the customer (optional)."""

    __tablename__ = "notifications"

    kind: Mapped[str] = mapped_column(String(20), default="info")
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(String(300))
    draft_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ShareLink(IdMixin, TimestampMixin, TenantMixin, Base):
    """Personal link without an account: the customer uploads photos and shares the location.

    Belongs to a draft (before an order exists) or an order. Only the hash of the token is stored.
    """

    __tablename__ = "share_links"

    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uploads: Mapped[int] = mapped_column(Integer, default=0)
    location: Mapped[dict[str, Any]] = mapped_column(default=dict)
    note: Mapped[str | None] = mapped_column(Text)
