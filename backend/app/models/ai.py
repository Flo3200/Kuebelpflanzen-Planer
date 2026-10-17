"""AI providers, models, per-tenant keys, usage records, versioned prompts, evaluation sets."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, OptionalTenantMixin, TenantMixin, TimestampMixin

PROVIDER_KINDS = ["anthropic", "openai", "openai_compatible", "fake"]


class AIProvider(IdMixin, TimestampMixin, Base):
    """Global provider configuration (admin). The platform key is stored encrypted."""

    __tablename__ = "ai_providers"

    name: Mapped[str] = mapped_column(String(80), unique=True, info={"list": True})
    kind: Mapped[str] = mapped_column(String(20), info={"enum": PROVIDER_KINDS, "list": True})
    base_url: Mapped[str | None] = mapped_column(String(300))
    api_key_enc: Mapped[str | None] = mapped_column(Text, info={"hidden": True})
    active: Mapped[bool] = mapped_column(Boolean, default=True, info={"list": True})


class AIModel(IdMixin, TimestampMixin, Base):
    """A model offered on the platform. Model names are data, never constants in the code."""

    __tablename__ = "ai_models"

    provider_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_providers.id", ondelete="CASCADE"))
    model_name: Mapped[str] = mapped_column(String(120))
    label: Mapped[str] = mapped_column(String(120))
    input_price_per_mtok: Mapped[float] = mapped_column(Float, default=0)
    output_price_per_mtok: Mapped[float] = mapped_column(Float, default=0)
    price_currency: Mapped[str] = mapped_column(String(3), default="USD")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    use_fallbacks: Mapped[bool] = mapped_column(Boolean, default=False)
    effort: Mapped[str | None] = mapped_column(String(10))
    supports_vision: Mapped[bool] = mapped_column(Boolean, default=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, default=True)
    max_output_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class TenantAIKey(IdMixin, TimestampMixin, TenantMixin, Base):
    """Bring-your-own-key of a tenant for one provider (encrypted, never sent to the frontend)."""

    __tablename__ = "tenant_ai_keys"

    provider_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_providers.id", ondelete="CASCADE"))
    api_key_enc: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(12))


class AIUsage(IdMixin, Base):
    __tablename__ = "ai_usage"
    __rls__ = "strict"
    __table_args__ = (Index("ix_ai_usage_tenant_time", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    function: Mapped[str] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    key_mode: Mapped[str] = mapped_column(String(10), default="platform")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_eur: Mapped[float] = mapped_column(Float, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(500))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromptTemplate(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    """Versioned prompt per AI function. Global (admin) or tenant override; the newest active
    version of the most specific level is used."""

    __tablename__ = "prompt_templates"

    function: Mapped[str] = mapped_column(String(40), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    system: Mapped[str] = mapped_column(Text)
    instructions: Mapped[str] = mapped_column(Text, default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class EvalSet(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    """Test set for the evaluation tool: photos with measured dimensions."""

    __tablename__ = "eval_sets"
    __rls__ = "strict"

    name: Mapped[str] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)


class EvalItem(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    __tablename__ = "eval_items"
    __rls__ = "strict"

    set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120))
    photo_file_ids: Mapped[list[Any]] = mapped_column(default=list)
    truth: Mapped[dict[str, Any]] = mapped_column(default=dict)


class EvalRun(IdMixin, TimestampMixin, OptionalTenantMixin, Base):
    __tablename__ = "eval_runs"
    __rls__ = "strict"

    set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("eval_sets.id", ondelete="CASCADE"), index=True
    )
    model_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ai_models.id", ondelete="CASCADE"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    items: Mapped[list[Any]] = mapped_column(default=list)
