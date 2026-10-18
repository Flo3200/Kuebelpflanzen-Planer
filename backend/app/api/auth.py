"""Login, logout, two-factor authentication, driver login, admin tenant switch."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, CurrentActor, cookie_kwargs
from app.core.config import get_config
from app.core.db import system_session
from app.core.errors import AppError, Forbidden, Unauthorized
from app.core.permissions import effective_permissions
from app.core.security import (
    decrypt,
    encrypt,
    hash_password,
    new_token,
    new_totp_secret,
    pin_lookup,
    token_hash,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models.core import AuthSession, LoginAttempt, OneTimeCode, Tenant, User
from app.settings.service import SettingsResolver

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str
    code: str | None = None


class PinLoginIn(BaseModel):
    tenant: str = Field(description="Betriebskennung (slug)")
    pin: str


class CodeIn(BaseModel):
    code: str


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=10)


class ActAsIn(BaseModel):
    tenant_id: uuid.UUID | None


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(db: Session, keys: list[str]) -> bool:
    cfg = get_config()
    since = datetime.now(UTC) - timedelta(minutes=cfg.login_window_minutes)
    for key in keys:
        limit = cfg.login_max_attempts_ip if key.startswith("ip:") else cfg.login_max_attempts
        failures = db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.key == key, LoginAttempt.success.is_(False), LoginAttempt.created_at > since)
        )
        if (failures or 0) >= limit:
            return True
    return False


def _note_attempt(db: Session, keys: list[str], success: bool) -> None:
    for key in keys:
        db.add(LoginAttempt(key=key, success=success))


def _requires_2fa(db: Session, user: User) -> bool:
    resolver = SettingsResolver(db, user.tenant_id)
    if user.role == "admin":
        return bool(resolver.get("security.admin_require_2fa"))
    if user.role in ("owner", "dispatcher"):
        return bool(resolver.get("security.owner_require_2fa"))
    return False


def create_session(
    db: Session,
    user: User,
    response: Response,
    request: Request,
    kind: str = "web",
    mfa_pending: bool = False,
) -> AuthSession:
    cfg = get_config()
    token = new_token()
    lifetime = (
        timedelta(days=cfg.driver_session_days)
        if kind in ("driver", "customer")
        else timedelta(hours=cfg.session_hours)
    )
    sess = AuthSession(
        token_hash=token_hash(token),
        user_id=user.id,
        kind=kind,
        csrf_token=new_token(24),
        mfa_pending=mfa_pending,
        expires_at=datetime.now(UTC) + lifetime,
        ip=_client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300],
    )
    db.add(sess)
    user.last_login_at = datetime.now(UTC)
    max_age = int(lifetime.total_seconds())
    response.set_cookie(SESSION_COOKIE, token, httponly=True, max_age=max_age, **cookie_kwargs())
    response.set_cookie(CSRF_COOKIE, sess.csrf_token, httponly=False, max_age=max_age, **cookie_kwargs())
    return sess


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response) -> dict:
    email = data.email.strip().lower()
    keys = [f"email:{email}", f"ip:{_client_ip(request)}"]
    with system_session() as db:
        if _rate_limited(db, keys):
            raise AppError("errors.login_rate_limited", status_code=429)
        user = db.scalar(select(User).where(func.lower(User.email) == email, User.deleted_at.is_(None)))
        ok = verify_password(data.password, user.password_hash if user else None)
        if not ok or user is None:
            _note_attempt(db, keys, False)
            db.commit()
            raise Unauthorized("errors.login_failed")
        if not user.is_active:
            raise Forbidden("errors.account_inactive")
        if user.tenant_id is not None:
            tenant = db.get(Tenant, user.tenant_id)
            if tenant is None or tenant.status != "active":
                raise Forbidden("errors.account_inactive")
        if user.totp_enabled:
            if not data.code:
                raise AppError("errors.mfa_required", status_code=401)
            if not verify_totp(decrypt(user.totp_secret_enc), data.code):
                _note_attempt(db, keys, False)
                db.commit()
                raise AppError("errors.mfa_invalid", status_code=401)
        mfa_pending = not user.totp_enabled and _requires_2fa(db, user)
        _note_attempt(db, keys, True)
        create_session(db, user, response, request, mfa_pending=mfa_pending)
        return {"ok": True, "mfa_setup_required": mfa_pending}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with system_session() as db:
            sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash(token)))
            if sess is not None:
                db.delete(sess)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(actor: CurrentActor, request: Request) -> dict:
    with system_session() as db:
        user = db.get(User, actor.user_id) if actor.user_id else None
        tenant = db.get(Tenant, actor.tenant_id) if actor.tenant_id else None
        sess = (
            db.get(AuthSession, request.state.auth_session_id)
            if hasattr(request.state, "auth_session_id")
            else None
        )
        return {
            "user": None
            if user is None
            else {
                "id": str(user.id),
                "name": user.name,
                "email": user.email,
                "role": user.role,
                "totp_enabled": user.totp_enabled,
                "language": user.language,
                "staff_member_id": str(user.staff_member_id) if user.staff_member_id else None,
            },
            "label": actor.label,
            "role": actor.role,
            "via": actor.via,
            "permissions": sorted(actor.permissions),
            "tenant": None
            if tenant is None
            else {"id": str(tenant.id), "name": tenant.name, "slug": tenant.slug},
            "acting_as_tenant": actor.role == "admin" and tenant is not None,
            "mfa_setup_required": bool(sess and sess.mfa_pending),
            "csrf_token": sess.csrf_token if sess else None,
        }


@router.post("/password")
def change_password(data: PasswordIn, actor: CurrentActor) -> dict:
    with system_session() as db:
        user = db.get(User, actor.user_id)
        if user is None or not verify_password(data.old_password, user.password_hash):
            raise Unauthorized("errors.login_failed")
        user.password_hash = hash_password(data.new_password)
    return {"ok": True}


@router.post("/2fa/setup")
def totp_setup(actor: CurrentActor) -> dict:
    with system_session() as db:
        user = db.get(User, actor.user_id)
        if user is None:
            raise Unauthorized()
        secret = new_totp_secret()
        user.totp_secret_enc = encrypt(secret)
        user.totp_enabled = False
        return {"secret": secret, "uri": totp_uri(secret, user.email or user.name)}


@router.post("/2fa/enable")
def totp_enable(data: CodeIn, actor: CurrentActor, request: Request) -> dict:
    with system_session() as db:
        user = db.get(User, actor.user_id)
        if user is None or not verify_totp(decrypt(user.totp_secret_enc), data.code):
            raise AppError("errors.mfa_invalid")
        user.totp_enabled = True
        sess_id = getattr(request.state, "auth_session_id", None)
        if sess_id:
            sess = db.get(AuthSession, sess_id)
            if sess:
                sess.mfa_pending = False
    return {"ok": True}


@router.post("/2fa/disable")
def totp_disable(data: CodeIn, actor: CurrentActor) -> dict:
    with system_session() as db:
        user = db.get(User, actor.user_id)
        if user is None or not verify_totp(decrypt(user.totp_secret_enc), data.code):
            raise AppError("errors.mfa_invalid")
        if _requires_2fa(db, user):
            raise Forbidden("errors.mfa_setup_required")
        user.totp_enabled = False
        user.totp_secret_enc = None
    return {"ok": True}


@router.post("/driver/pin")
def driver_pin_login(data: PinLoginIn, request: Request, response: Response) -> dict:
    slug = data.tenant.strip().lower()
    keys = [f"pin:{slug}", f"ip:{_client_ip(request)}"]
    with system_session() as db:
        if _rate_limited(db, keys):
            raise AppError("errors.login_rate_limited", status_code=429)
        user = db.scalar(
            select(User).where(
                User.pin_lookup == pin_lookup(slug, data.pin.strip()), User.deleted_at.is_(None)
            )
        )
        if user is None or not verify_password(data.pin.strip(), user.pin_hash) or not user.is_active:
            _note_attempt(db, keys, False)
            db.commit()
            raise Unauthorized("errors.login_failed")
        _note_attempt(db, keys, True)
        create_session(db, user, response, request, kind="driver")
        return {"ok": True}


@router.post("/link/{code}")
def link_login(code: str, request: Request, response: Response) -> dict:
    """Personal driver link: /fahrer/login/<code> posts here."""
    now = datetime.now(UTC)
    with system_session() as db:
        otc = db.scalar(
            select(OneTimeCode).where(
                OneTimeCode.code_hash == token_hash(code), OneTimeCode.purpose == "driver_link"
            )
        )
        if otc is None or otc.expires_at < now or (otc.used_at and not otc.reusable) or otc.user_id is None:
            raise Unauthorized("errors.code_invalid")
        user = db.get(User, otc.user_id)
        if user is None or not user.is_active:
            raise Unauthorized("errors.code_invalid")
        otc.used_at = now
        create_session(db, user, response, request, kind="driver")
        return {"ok": True}


@router.post("/customer/{code}")
def customer_link_login(code: str, request: Request, response: Response) -> dict:
    """Personal link of a customer: /kunde/login/<code> posts here (customer portal)."""
    now = datetime.now(UTC)
    with system_session() as db:
        otc = db.scalar(
            select(OneTimeCode).where(
                OneTimeCode.code_hash == token_hash(code), OneTimeCode.purpose == "customer_link"
            )
        )
        if otc is None or otc.expires_at < now or otc.user_id is None:
            raise Unauthorized("errors.code_invalid")
        user = db.get(User, otc.user_id)
        if user is None or not user.is_active or user.role != "customer" or user.customer_id is None:
            raise Unauthorized("errors.code_invalid")
        tenant = db.get(Tenant, user.tenant_id)
        if (
            tenant is None
            or tenant.status != "active"
            or not bool(SettingsResolver(db, tenant.id).get("portal.enabled"))
        ):
            raise Unauthorized("errors.code_invalid")
        otc.used_at = now
        create_session(db, user, response, request, kind="customer")
        return {"ok": True}


@router.post("/act-as")
def act_as(data: ActAsIn, actor: CurrentActor, request: Request) -> dict:
    """Platform admin switches into a tenant (or back to platform view)."""
    if actor.role != "admin":
        raise Forbidden()
    with system_session() as db:
        if data.tenant_id is not None and db.get(Tenant, data.tenant_id) is None:
            raise AppError("errors.not_found", status_code=404)
        sess = db.get(AuthSession, request.state.auth_session_id)
        if sess is None:
            raise Unauthorized()
        sess.acting_tenant_id = data.tenant_id
    return {"ok": True}


def user_permissions(user: User) -> list[str]:
    return sorted(effective_permissions(user.role, user.extra_permissions, user.revoked_permissions))
