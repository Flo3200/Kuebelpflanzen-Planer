"""Agents: enrolment links, code exchange, tokens (revoke), call log, confirmations; /agent/README.md."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.readme import render
from app.agents.tokens import ADMIN_SCOPES, TENANT_SCOPES, create_enrolment, platform_mode, redeem, token_dict
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.db import system_session
from app.core.errors import AppError, NotFound
from app.models.core import Tenant
from app.models.platform import AgentCall, AgentToken, PendingConfirmation

router = APIRouter(prefix="/api/agents", tags=["agents"])
public_router = APIRouter(tags=["agents"])


def _kind(actor: Actor) -> str:
    return "tenant" if actor.tenant_id is not None else "admin"


def _require(actor: Actor) -> None:
    actor.require("tenant.agents" if actor.tenant_id is not None else "platform.agents")


@router.get("/meta")
def meta(actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Scopes that can be given and the platform mode."""
    _require(actor)
    kind = _kind(actor)
    return {
        "kind": kind,
        "scopes": list(TENANT_SCOPES if kind == "tenant" else ADMIN_SCOPES),
        "mode": platform_mode(db),
        "readme_url": f"{get_config().base_url}/agent/README.md",
    }


class LinkIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    scopes: list[str] = Field(min_length=1)
    token_days: int | None = Field(default=None, ge=1, le=365)
    link_hours: int = Field(default=24, ge=1, le=168)


@router.post("/links", status_code=201)
def create_link(data: LinkIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    """Enrolment link with a one-time code for an agent."""
    kind = _kind(actor)
    code, otc = create_enrolment(
        db,
        actor,
        name=data.name,
        scopes=data.scopes,
        kind=kind,
        token_days=data.token_days,
        link_hours=data.link_hours,
    )
    audit.record(
        db,
        actor,
        tenant_id=actor.tenant_id,
        entity="agent_link",
        entity_id=otc.id,
        action="create",
        new={"name": data.name, "scopes": data.scopes, "kind": kind},
    )
    base = get_config().base_url
    return {
        "url": f"{base}/agent/enroll/{code}",
        "code": code,
        "expires_at": otc.expires_at,
        "kind": kind,
        "curl": f"curl -s -X POST {base}/agent/enroll/{code}",
        "readme_url": f"{base}/agent/README.md",
    }


@router.get("/tokens")
def list_tokens(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    _require(actor)
    q = select(AgentToken).order_by(AgentToken.created_at.desc())
    q = (
        q.where(AgentToken.tenant_id == actor.tenant_id)
        if actor.tenant_id
        else q.where(AgentToken.tenant_id.is_(None))
    )
    return [token_dict(t) for t in db.scalars(q)]


@router.post("/tokens/{token_id}/revoke")
def revoke(token_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _require(actor)
    t = db.get(AgentToken, token_id)
    if t is None or t.tenant_id != actor.tenant_id:
        raise NotFound()
    if t.revoked_at is None:
        t.revoked_at = datetime.now(UTC)
        audit.record(db, actor, tenant_id=t.tenant_id, entity="agent_token", entity_id=t.id, action="revoke")
    return token_dict(t)


@router.get("/calls")
def calls(
    actor: CurrentActor, db: DB, token_id: uuid.UUID | None = None, limit: int = 200
) -> list[dict[str, Any]]:
    """Call log of the agents."""
    _require(actor)
    q = select(AgentCall, AgentToken.name).join(AgentToken, AgentToken.id == AgentCall.token_id)
    q = (
        q.where(AgentToken.tenant_id == actor.tenant_id)
        if actor.tenant_id
        else q.where(AgentToken.tenant_id.is_(None))
    )
    if token_id:
        q = q.where(AgentCall.token_id == token_id)
    rows = db.execute(q.order_by(AgentCall.created_at.desc()).limit(min(limit, 1000))).all()
    return [
        {
            "id": c.id,
            "token": n,
            "method": c.method,
            "path": c.path,
            "status": c.status,
            "duration_ms": c.duration_ms,
            "acting_tenant_id": c.acting_tenant_id,
            "at": c.created_at,
        }
        for c, n in rows
    ]


@router.get("/confirmations")
def confirmations(actor: CurrentActor, db: DB, status: str | None = "pending") -> list[dict[str, Any]]:
    """Actions of agents waiting for a human."""
    _require(actor)
    q = select(PendingConfirmation, AgentToken.name).outerjoin(
        AgentToken, AgentToken.id == PendingConfirmation.token_id
    )
    q = (
        q.where(PendingConfirmation.tenant_id == actor.tenant_id)
        if actor.tenant_id
        else q.where(PendingConfirmation.tenant_id.is_(None))
    )
    if status:
        q = q.where(PendingConfirmation.status == status)
    rows = db.execute(q.order_by(PendingConfirmation.requested_at.desc()).limit(200)).all()
    return [
        {
            "id": p.id,
            "token": n,
            "action": p.action,
            "payload": p.payload,
            "status": p.status,
            "requested_at": p.requested_at,
            "expires_at": p.expires_at,
            "decided_at": p.decided_at,
            "used_at": p.used_at,
        }
        for p, n in rows
    ]


class DecideIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/confirmations/{conf_id}/decide")
def decide(conf_id: uuid.UUID, data: DecideIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    _require(actor)
    if actor.via == "agent":
        raise AppError("errors.forbidden", status_code=403)  # agents never confirm themselves
    p = db.get(PendingConfirmation, conf_id)
    if p is None or p.tenant_id != actor.tenant_id:
        raise NotFound()
    if p.status != "pending":
        raise AppError("errors.already_decided", status_code=409)
    p.status = "approved" if data.approve else "rejected"
    p.decided_by = actor.user_id
    p.decided_at = datetime.now(UTC)
    p.note = data.note
    audit.record(
        db,
        actor,
        tenant_id=p.tenant_id,
        entity="agent_confirmation",
        entity_id=p.id,
        action=p.status,
        new={"action": p.action, "payload": p.payload},
    )
    return {"id": p.id, "status": p.status}


# ---------------------------------------------------------------- public: README and enrolment


@public_router.get("/agent/README.md", response_class=PlainTextResponse, include_in_schema=False)
def agent_readme(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        render(request.app, get_config().base_url), media_type="text/markdown; charset=utf-8"
    )


@public_router.get("/agent/enroll/{code}", response_class=PlainTextResponse, include_in_schema=False)
def enroll_info(code: str) -> PlainTextResponse:
    base = get_config().base_url
    text = (
        "# Einwahl\n\nDieser Link enthält einen einmaligen Code. Tausche ihn gegen ein Token:\n\n"
        f"    curl -s -X POST {base}/agent/enroll/{code}\n\n"
        f"Anleitung: {base}/agent/README.md\n"
    )
    return PlainTextResponse(text, media_type="text/markdown; charset=utf-8")


@public_router.post("/agent/enroll/{code}")
def enroll(code: str, request: Request) -> dict[str, Any]:
    """Exchange the one-time code for a bearer token."""
    ip = request.client.host if request.client else None
    plain, row = redeem(code, ip, request.headers.get("user-agent"))
    tenant = None
    if row.tenant_id:
        with system_session() as db:
            t = db.get(Tenant, row.tenant_id)
            tenant = {"id": str(t.id), "name": t.name} if t else None
    base = get_config().base_url
    return {
        "token": plain,
        "token_type": "bearer",
        "scopes": row.scopes,
        "kind": row.kind,
        "expires_at": row.expires_at,
        "tenant": tenant,
        "api_base": f"{base}/api",
        "readme": f"{base}/agent/README.md",
    }
