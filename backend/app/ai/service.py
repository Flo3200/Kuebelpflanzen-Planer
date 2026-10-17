"""Calling AI for a tenant: model per function, keys (platform or BYOK), spending limit, prompt
versions, structured-output validation with retries, fallback model, usage recording."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.functions import DEFAULT_PROMPTS, SCHEMAS
from app.ai.providers import AIRequest, AIResponse, ProviderError, get_provider
from app.core.config import get_config
from app.core.db import system_session
from app.core.errors import AppError
from app.core.security import decrypt
from app.models.ai import AIModel, AIProvider, AIUsage, PromptTemplate, TenantAIKey
from app.settings.service import SettingsResolver


@dataclass
class ResolvedModel:
    model: AIModel
    provider: AIProvider


def resolve_model(
    db: Session, resolver: SettingsResolver, function: str, *, fallback: bool = False
) -> ResolvedModel:
    key = "ai.fallback_model" if fallback else f"ai.model.{function}"
    wanted = resolver.get(key)
    model = None
    if wanted:
        try:
            model = db.get(AIModel, uuid.UUID(str(wanted)))
        except ValueError:
            model = db.scalar(
                select(AIModel).where(AIModel.model_name == str(wanted), AIModel.active.is_(True))
            )
    if model is None and not fallback:
        model = db.scalar(
            select(AIModel).where(AIModel.is_default.is_(True), AIModel.active.is_(True)).limit(1)
        )
    if model is None or not model.active:
        raise AppError("errors.ai_not_configured")
    provider = db.get(AIProvider, model.provider_id)
    if provider is None or not provider.active:
        raise AppError("errors.ai_not_configured")
    return ResolvedModel(model, provider)


def api_key_for(
    db: Session, tenant_id: uuid.UUID | None, resolver: SettingsResolver, provider: AIProvider
) -> tuple[str | None, str]:
    """Returns (key, key_mode). BYOK tenants use their own key; otherwise the platform key."""
    if provider.kind == "fake":
        return None, "platform"
    if tenant_id is not None and resolver.get("ai.key_mode") == "byok":
        row = db.scalar(
            select(TenantAIKey).where(
                TenantAIKey.tenant_id == tenant_id, TenantAIKey.provider_id == provider.id
            )
        )
        return (decrypt(row.api_key_enc) if row else None), "byok"
    key = decrypt(provider.api_key_enc)
    if not key:
        cfg = get_config()
        key = {"anthropic": cfg.anthropic_api_key, "openai": cfg.openai_api_key}.get(provider.kind) or None
    return key, "platform"


def month_spend_eur(db: Session, tenant_id: uuid.UUID) -> float:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return float(
        db.scalar(
            select(func.coalesce(func.sum(AIUsage.cost_eur), 0)).where(
                AIUsage.tenant_id == tenant_id, AIUsage.created_at >= start, AIUsage.key_mode == "platform"
            )
        )
        or 0
    )


def spend_status(db: Session, tenant_id: uuid.UUID, resolver: SettingsResolver) -> dict[str, Any]:
    limit = float(resolver.get("ai.monthly_limit_eur"))
    spent = month_spend_eur(db, tenant_id)
    warn_at = limit * resolver.get("ai.warn_pct") / 100
    return {
        "limit_eur": limit,
        "spent_eur": round(spent, 4),
        "warn": spent >= warn_at,
        "blocked": limit > 0 and spent >= limit,
    }


def cost_eur(model: AIModel, resolver: SettingsResolver, input_tokens: int, output_tokens: int) -> float:
    cost = (input_tokens * model.input_price_per_mtok + output_tokens * model.output_price_per_mtok) / 1e6
    if model.price_currency == "USD":
        cost *= resolver.platform_value("ai.usd_to_eur")
    return cost


def prompt_for(db: Session, tenant_id: uuid.UUID | None, function: str) -> dict[str, str]:
    """Newest active prompt of the tenant, else of the platform, else the built-in default."""
    for tid in ([tenant_id] if tenant_id else []) + [None]:
        cond = PromptTemplate.tenant_id.is_(None) if tid is None else PromptTemplate.tenant_id == tid
        row = db.scalar(
            select(PromptTemplate)
            .where(cond, PromptTemplate.function == function, PromptTemplate.active.is_(True))
            .order_by(PromptTemplate.version.desc())
            .limit(1)
        )
        if row is not None:
            return {"system": row.system, "instructions": row.instructions, "version": str(row.version)}
    return {**DEFAULT_PROMPTS.get(function, {"system": "", "instructions": ""}), "version": "0"}


def validate(schema: dict[str, Any] | None, data: Any, path: str = "$") -> list[str]:
    """Small JSON-schema check (types, required, nested objects/arrays) for model outputs."""
    if schema is None:
        return []
    errors: list[str] = []
    types = schema.get("type")
    types = types if isinstance(types, list) else [types] if types else []
    checks = {
        "object": lambda x: isinstance(x, dict),
        "array": lambda x: isinstance(x, list),
        "string": lambda x: isinstance(x, str),
        "number": lambda x: isinstance(x, (int, float)) and not isinstance(x, bool),
        "integer": lambda x: isinstance(x, int) and not isinstance(x, bool),
        "boolean": lambda x: isinstance(x, bool),
        "null": lambda x: x is None,
    }
    if types and not any(checks.get(t, lambda _: True)(data) for t in types):
        return [f"{path}: expected {'/'.join(types)}"]
    if isinstance(data, dict):
        for req in schema.get("required", []):
            if req not in data:
                errors.append(f"{path}.{req}: missing")
        for k, sub in schema.get("properties", {}).items():
            if k in data:
                errors += validate(sub, data[k], f"{path}.{k}")
    if isinstance(data, list) and "items" in schema:
        for i, item in enumerate(data[:200]):
            errors += validate(schema["items"], item, f"{path}[{i}]")
    return errors


def _record(
    tenant_id, function, provider, model, key_mode, resp: AIResponse | None, cost, ok, error, job_id
) -> None:
    # recorded in its own transaction so failures are kept even if the caller rolls back
    with system_session() as db:
        db.add(
            AIUsage(
                tenant_id=tenant_id,
                function=function,
                provider=provider.name,
                model=model.model_name,
                key_mode=key_mode,
                input_tokens=resp.input_tokens if resp else 0,
                output_tokens=resp.output_tokens if resp else 0,
                cost_eur=round(cost, 6),
                duration_ms=resp.duration_ms if resp else 0,
                success=ok,
                error=(error or "")[:500] or None,
                job_id=job_id,
            )
        )


def call(
    db: Session,
    tenant_id: uuid.UUID | None,
    function: str,
    text: str,
    *,
    images: list | None = None,
    context: dict[str, Any] | None = None,
    job_id: uuid.UUID | None = None,
    schema: dict[str, Any] | None = None,
    model_id: uuid.UUID | None = None,
) -> tuple[AIResponse, AIModel]:
    """Run one AI function for a tenant. model_id forces a model (evaluation tool)."""
    resolver = SettingsResolver(db, tenant_id)
    if tenant_id is not None:
        status = spend_status(db, tenant_id, resolver)
        if status["blocked"] and resolver.get("ai.key_mode") != "byok":
            raise AppError("errors.ai_limit", status_code=402)
    prompt = prompt_for(db, tenant_id, function)
    schema = schema if schema is not None else SCHEMAS.get(function)
    request = AIRequest(
        function=function,
        system=prompt["system"],
        text=(prompt.get("instructions", "") + "\n\n" + text).strip(),
        images=images or [],
        schema=schema,
        context=context or {},
    )
    attempts = int(resolver.get("ai.max_retries")) + 1
    last_error = "unknown"
    for use_fallback in (False, True):
        try:
            if model_id is not None and not use_fallback:
                forced = db.get(AIModel, model_id)
                if forced is None:
                    raise AppError("errors.ai_not_configured")
                resolved = ResolvedModel(forced, db.get(AIProvider, forced.provider_id))
            else:
                resolved = resolve_model(db, resolver, function, fallback=use_fallback)
        except AppError:
            if use_fallback:
                break
            raise
        provider = get_provider(resolved.provider.kind, resolved.provider.base_url)
        key, key_mode = api_key_for(db, tenant_id, resolver, resolved.provider)
        request.effort = resolved.model.effort
        options = {"fallbacks": resolved.model.use_fallbacks}
        for attempt in range(attempts):
            try:
                resp = provider.complete(resolved.model.model_name, request, key, options)
            except ProviderError as exc:
                last_error = str(exc)
                _record(
                    tenant_id,
                    function,
                    resolved.provider,
                    resolved.model,
                    key_mode,
                    None,
                    0,
                    False,
                    last_error,
                    job_id,
                )
                break  # provider problem: try the fallback model
            cost = cost_eur(resolved.model, resolver, resp.input_tokens, resp.output_tokens)
            problems = ["refused"] if resp.refused else validate(schema, resp.data) if schema else []
            if schema and resp.data is None and not resp.refused:
                problems = ["no JSON"]
            _record(
                tenant_id,
                function,
                resolved.provider,
                resolved.model,
                key_mode,
                resp,
                cost,
                not problems,
                "; ".join(problems[:5]) or None,
                job_id,
            )
            if not problems:
                return resp, resolved.model
            last_error = "; ".join(problems[:5])
            if resp.refused:
                break
            request.text = (
                prompt.get("instructions", "")
                + "\n\n"
                + text
                + f"\n\nDie letzte Antwort war ungültig ({last_error}). Antworte exakt nach dem Schema."
            ).strip()
    raise AppError("errors.ai_failed", detail=last_error[:200])
