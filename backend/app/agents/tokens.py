"""Agent tokens: enrolment (one-time code -> token), bearer authentication, scopes, platform mode.

Platform mode (setting platform.mode, enforced here on the server):
- test:       an admin agent may do everything the admin account may do, also inside a tenant
              (header X-KP-Tenant: <tenant id>).
- production: admin agent tokens are limited to the scope "admin_support". They cannot act for
              tenants (X-KP-Tenant is refused) and see no tenant data (no RLS bypass).
Tenant agents always work only inside their own tenant, with the permissions of their scopes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.db import system_session
from app.core.errors import AppError, Forbidden, Unauthorized
from app.core.permissions import AGENT_SCOPES, ALL_PERMISSIONS
from app.core.security import new_token, token_hash
from app.models.core import OneTimeCode, Tenant
from app.models.platform import AgentCall, AgentToken
from app.settings.service import SettingsResolver

TENANT_SCOPES = ("read", "drafts", "masterdata", "planning", "settings")
ADMIN_SCOPES = ("admin_support", "admin_full")
TOKEN_PREFIX = "kpa_"


def platform_mode(db: Session) -> str:
    return str(SettingsResolver(db, None).get("platform.mode"))


def scopes_for(kind: str) -> tuple[str, ...]:
    return ADMIN_SCOPES if kind == "admin" else TENANT_SCOPES


def create_enrolment(
    db: Session,
    actor: Actor,
    *,
    name: str,
    scopes: list[str],
    kind: str,
    token_days: int | None,
    link_hours: int = 24,
) -> tuple[str, OneTimeCode]:
    allowed = scopes_for(kind)
    bad = [s for s in scopes if s not in allowed]
    if bad or not scopes:
        raise AppError("errors.agent_scope", scopes=", ".join(bad) or "–")
    if kind == "admin":
        actor.require("platform.agents")
        tenant_id = None
    else:
        actor.require("tenant.agents")
        tenant_id = actor.require_tenant()
    code = new_token(18)
    days = token_days or int(SettingsResolver(db, tenant_id).get("agents.token_days"))
    otc = OneTimeCode(
        tenant_id=tenant_id,
        purpose="agent_enrol",
        code_hash=token_hash(code),
        payload={"name": name, "scopes": scopes, "kind": kind, "days": days},
        created_by=actor.user_id,
        expires_at=datetime.now(UTC) + timedelta(hours=link_hours),
    )
    db.add(otc)
    db.flush()
    return code, otc


def redeem(code: str, ip: str | None, user_agent: str | None) -> tuple[str, AgentToken]:
    """Exchange a one-time enrolment code for a token (the plain token is returned only once)."""
    now = datetime.now(UTC)
    with system_session() as db:
        otc = db.scalar(
            select(OneTimeCode)
            .where(OneTimeCode.code_hash == token_hash(code), OneTimeCode.purpose == "agent_enrol")
            .with_for_update()
        )
        if otc is None or otc.used_at is not None or otc.expires_at < now:
            raise Unauthorized("errors.code_invalid")
        otc.used_at = now
        p = otc.payload
        plain = TOKEN_PREFIX + new_token(32)
        row = AgentToken(
            tenant_id=otc.tenant_id,
            name=p.get("name") or "Agent",
            kind=p.get("kind", "tenant"),
            token_hash=token_hash(plain),
            prefix=plain[:12],
            scopes=list(p.get("scopes", [])),
            created_by=otc.created_by,
            expires_at=now + timedelta(days=int(p.get("days", 30))),
            enrolled_ip=ip,
            enrolled_agent=(user_agent or "")[:300] or None,
        )
        db.add(row)
        db.flush()
        db.expunge(row)
        return plain, row


def _permissions(scopes: list[str]) -> frozenset[str]:
    perms: set[str] = set()
    for s in scopes:
        perms |= AGENT_SCOPES.get(s, frozenset())
    return frozenset(perms)


def authenticate(request: Request, token: str) -> Actor | None:
    """Bearer authenticator for agent tokens (registered in app.api.deps.BEARER_AUTHENTICATORS)."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    now = datetime.now(UTC)
    with system_session() as db:
        row = db.scalar(select(AgentToken).where(AgentToken.token_hash == token_hash(token)))
        if row is None or row.revoked_at is not None or row.expires_at < now:
            return None
        rate = row.rate_per_min or int(SettingsResolver(db, row.tenant_id).get("agents.rate_per_min"))
        recent = db.scalar(
            select(func.count())
            .select_from(AgentCall)
            .where(AgentCall.token_id == row.id, AgentCall.created_at > now - timedelta(minutes=1))
        )
        if (recent or 0) >= rate:
            raise AppError("errors.rate_limited", status_code=429)
        wanted_tenant = request.headers.get("x-kp-tenant")
        confirmation = request.headers.get("x-kp-confirmation")
        request.state.agent_token_id = row.id
        if row.kind == "admin":
            mode = platform_mode(db)
            if mode == "production":
                if wanted_tenant:
                    raise Forbidden("errors.production_admin_agent")
                # admin support only: platform data, no tenant data, no RLS bypass
                perms = _permissions(row.scopes) & AGENT_SCOPES["admin_support"]
                return Actor(
                    user_id=None,
                    label=f"Agent {row.name}",
                    role="agent_admin",
                    tenant_id=None,
                    permissions=perms,
                    via="agent",
                    agent_token_id=row.id,
                    confirmation_id=confirmation,
                )
            tenant_id = None
            if wanted_tenant:
                try:
                    tenant_id = uuid.UUID(wanted_tenant)
                except ValueError as exc:
                    raise Forbidden("errors.not_found") from exc
                if db.get(Tenant, tenant_id) is None:
                    raise Forbidden("errors.not_found")
            perms = frozenset(ALL_PERMISSIONS) if "admin_full" in row.scopes else _permissions(row.scopes)
            return Actor(
                user_id=None,
                label=f"Agent {row.name}",
                role="admin",
                tenant_id=tenant_id,
                permissions=perms,
                via="agent",
                agent_token_id=row.id,
                confirmation_id=confirmation,
            )
        if wanted_tenant and wanted_tenant != str(row.tenant_id):
            raise Forbidden("errors.forbidden")
        tenant = db.get(Tenant, row.tenant_id)
        if tenant is None or tenant.status != "active" or tenant.deleted_at is not None:
            return None
        perms = frozenset(p for p in _permissions(row.scopes) if not p.startswith("platform."))
        return Actor(
            user_id=None,
            label=f"Agent {row.name}",
            role="agent",
            tenant_id=row.tenant_id,
            permissions=perms,
            via="agent",
            agent_token_id=row.id,
            confirmation_id=confirmation,
        )


def log_call(
    token_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    acting_tenant: uuid.UUID | None,
    method: str,
    path: str,
    status: int,
    duration_ms: int,
) -> None:
    with system_session() as db:
        db.add(
            AgentCall(
                tenant_id=tenant_id,
                token_id=token_id,
                method=method,
                path=path[:300],
                status=status,
                duration_ms=duration_ms,
                acting_tenant_id=acting_tenant,
            )
        )
        row = db.get(AgentToken, token_id)
        if row is not None:
            row.calls = (row.calls or 0) + 1
            row.last_used_at = datetime.now(UTC)


def token_dict(t: AgentToken) -> dict[str, Any]:
    now = datetime.now(UTC)
    state = "revoked" if t.revoked_at else "expired" if t.expires_at < now else "active"
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "prefix": t.prefix,
        "scopes": t.scopes,
        "created_at": t.created_at,
        "expires_at": t.expires_at,
        "revoked_at": t.revoked_at,
        "last_used_at": t.last_used_at,
        "calls": t.calls,
        "state": state,
        "enrolled_ip": t.enrolled_ip,
        "enrolled_agent": t.enrolled_agent,
    }
