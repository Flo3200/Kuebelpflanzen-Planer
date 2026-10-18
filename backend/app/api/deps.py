"""Request dependencies: authentication, CSRF, database session with RLS context."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_config
from app.core.context import Actor
from app.core.db import session_scope, system_session
from app.core.errors import AppError, Forbidden, Unauthorized
from app.core.permissions import effective_permissions
from app.core.security import token_hash
from app.models.core import AuthSession, Tenant, User

SESSION_COOKIE = "kp_session"
CSRF_COOKIE = "kp_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Bearer-token authenticators (agent tokens etc.) register here: fn(request, token) -> Actor | None
BEARER_AUTHENTICATORS: list[Callable[[Request, str], Actor | None]] = []

# The only paths a customer login may use
CUSTOMER_PATHS = ("/api/portal/", "/api/auth/", "/api/files/")

# Paths a session with pending 2FA setup may use
MFA_SETUP_PATHS = ("/api/auth/me", "/api/auth/logout", "/api/auth/2fa/")


def _session_actor(request: Request) -> Actor | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    now = datetime.now(UTC)
    with system_session() as db:
        sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        if sess is None or sess.expires_at < now:
            return None
        user = db.get(User, sess.user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            return None
        if request.method not in SAFE_METHODS:
            sent = request.headers.get(CSRF_HEADER, "")
            if not sent or sent != sess.csrf_token:
                raise AppError("errors.csrf", status_code=403)
        if sess.mfa_pending and not request.url.path.startswith(MFA_SETUP_PATHS):
            raise Forbidden("errors.mfa_setup_required")
        if sess.last_seen_at is None or now - sess.last_seen_at > timedelta(minutes=5):
            sess.last_seen_at = now
        tenant_id = user.tenant_id
        if user.role == "admin" and sess.acting_tenant_id is not None:
            tenant_id = sess.acting_tenant_id
        if tenant_id is not None and user.role != "admin":
            tenant = db.get(Tenant, tenant_id)
            if tenant is None or tenant.status != "active" or tenant.deleted_at is not None:
                return None
        request.state.auth_session_id = sess.id
        return Actor(
            user_id=user.id,
            label=user.name,
            role=user.role,
            tenant_id=tenant_id,
            permissions=effective_permissions(user.role, user.extra_permissions, user.revoked_permissions),
            via="ui",
            staff_member_id=user.staff_member_id,
            customer_id=user.customer_id if user.role == "customer" else None,
        )


def get_optional_actor(request: Request) -> Actor | None:
    if hasattr(request.state, "actor"):
        return request.state.actor
    actor: Actor | None = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        for authenticate in BEARER_AUTHENTICATORS:
            actor = authenticate(request, token)
            if actor is not None:
                break
        if actor is None:
            raise Unauthorized("errors.code_invalid")
    else:
        actor = _session_actor(request)
        if actor is not None and request.headers.get("x-kp-via") == "settings_ai":
            actor = actor.with_via("settings_ai")
    if actor is not None and actor.role == "customer" and not request.url.path.startswith(CUSTOMER_PATHS):
        # customers only reach the portal (and their own files, checked there) - never staff endpoints
        raise Forbidden()
    request.state.actor = actor
    return actor


def get_actor(request: Request) -> Actor:
    actor = get_optional_actor(request)
    if actor is None:
        raise Unauthorized()
    return actor


def get_db(actor: Annotated[Actor, Depends(get_actor)]) -> Iterator[Session]:
    with session_scope(actor.rls) as db:
        yield db


CurrentActor = Annotated[Actor, Depends(get_actor)]
DB = Annotated[Session, Depends(get_db, scope="function")]


def require(*perms: str):
    """Dependency factory: `dependencies=[require("staff.write")]`."""

    def _check(actor: CurrentActor) -> Actor:
        actor.require(*perms)
        return actor

    return Depends(_check)


def tenant_id_of(actor: Actor) -> uuid.UUID:
    return actor.require_tenant()


def cookie_kwargs() -> dict:
    return {"secure": get_config().cookie_secure, "samesite": "lax", "path": "/"}
