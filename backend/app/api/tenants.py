"""Tenants (admin), own tenant profile, users of a tenant, platform admins."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.crud import ENTITIES, EntitySpec, apply_values, build_schemas, row_dict
from app.api.deps import DB, CurrentActor
from app.core import audit
from app.core.config import get_config
from app.core.context import Actor
from app.core.db import system_session
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS
from app.core.security import hash_password, new_token, pin_lookup, token_hash
from app.models.core import OneTimeCode, Tenant, User

router = APIRouter(tags=["tenants"])

TENANT_SPEC = EntitySpec(
    "tenant", Tenant, "platform.tenants", "platform.tenants", search=("name", "slug", "city")
)
TenantCreate, TenantUpdate, TenantRead = build_schemas(TENANT_SPEC)
ENTITIES["tenant"] = TENANT_SPEC


def slugify(text: str) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:60] or "betrieb"


class OwnerIn(BaseModel):
    name: str
    email: str
    password: str = Field(min_length=10)


class TenantCreateIn(BaseModel):
    tenant: TenantCreate  # type: ignore[valid-type]
    owner: OwnerIn | None = None


def create_tenant(db: Session, actor: Actor, values: dict[str, Any], owner: OwnerIn | None) -> Tenant:
    values = dict(values)
    slug = values.get("slug") or slugify(values["name"])
    if db.scalar(select(Tenant).where(Tenant.slug == slug)) is not None:
        raise Conflict("errors.slug_taken")
    tenant = Tenant(slug=slug)
    values.pop("slug", None)
    apply_values(TENANT_SPEC, tenant, values)
    db.add(tenant)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tenant.id,
        entity="tenant",
        entity_id=tenant.id,
        action="create",
        new=row_dict(TENANT_SPEC, tenant),
    )
    if owner is not None:
        create_user(db, actor, tenant.id, owner.name, owner.email, "owner", password=owner.password)
    return tenant


def create_user(
    db: Session,
    actor: Actor,
    tenant_id: uuid.UUID | None,
    name: str,
    email: str | None,
    role: str,
    password: str | None = None,
    staff_member_id: uuid.UUID | None = None,
) -> User:
    if email:
        email = email.strip().lower()
        # emails are unique platform-wide; RLS would hide other tenants' users, so check globally
        with system_session() as sysdb:
            if sysdb.scalar(select(User.id).where(func.lower(User.email) == email)) is not None:
                raise Conflict("errors.email_taken")
    if role not in ROLE_PERMISSIONS:
        raise AppError("errors.validation")
    user = User(
        tenant_id=tenant_id,
        name=name,
        email=email,
        role=role,
        password_hash=hash_password(password) if password else None,
        staff_member_id=staff_member_id,
        extra_permissions=[],
        revoked_permissions=[],
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        actor,
        tenant_id=tenant_id,
        entity="user",
        entity_id=user.id,
        action="create",
        new={"name": name, "email": email, "role": role},
    )
    return user


# ------------------------------------------------------------------ admin: tenants


@router.get("/api/admin/tenants", response_model=list[TenantRead])
def admin_list_tenants(actor: CurrentActor, db: DB) -> list[Any]:
    actor.require("platform.tenants")
    return list(db.scalars(select(Tenant).where(Tenant.deleted_at.is_(None)).order_by(Tenant.name)))


@router.post("/api/admin/tenants", response_model=TenantRead, status_code=201)
def admin_create_tenant(data: TenantCreateIn, actor: CurrentActor, db: DB) -> Any:
    actor.require("platform.tenants")
    return create_tenant(db, actor, data.tenant.model_dump(), data.owner)  # type: ignore[attr-defined]


@router.patch("/api/admin/tenants/{tenant_id}", response_model=TenantRead)
def admin_update_tenant(tenant_id: uuid.UUID, data: TenantUpdate, actor: CurrentActor, db: DB) -> Any:  # type: ignore[valid-type]
    actor.require("platform.tenants")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound()
    changes = apply_values(TENANT_SPEC, tenant, data.model_dump(exclude_unset=True))  # type: ignore[attr-defined]
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=tenant.id,
            entity="tenant",
            entity_id=tenant.id,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    return tenant


@router.delete("/api/admin/tenants/{tenant_id}")
def admin_delete_tenant(tenant_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict:
    actor.require("platform.tenants")
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise NotFound()
    tenant.deleted_at = datetime.now(UTC)
    tenant.status = "suspended"
    audit.record(db, actor, tenant_id=tenant.id, entity="tenant", entity_id=tenant.id, action="delete")
    return {"ok": True}


@router.get("/api/admin/tenants/{tenant_id}/stats")
def admin_tenant_stats(tenant_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict:
    actor.require("platform.tenants")
    from app.api.stats import tenant_counts

    return tenant_counts(db, tenant_id)


# ------------------------------------------------------------------ own tenant


@router.get("/api/tenant", response_model=TenantRead)
def get_own_tenant(actor: CurrentActor, db: DB) -> Any:
    tid = actor.require_tenant()
    actor.require("tenant.view")
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise NotFound()
    return tenant


@router.patch("/api/tenant", response_model=TenantRead)
def update_own_tenant(data: TenantUpdate, actor: CurrentActor, db: DB) -> Any:  # type: ignore[valid-type]
    tid = actor.require_tenant()
    actor.require("tenant.profile")
    tenant = db.get(Tenant, tid)
    if tenant is None:
        raise NotFound()
    values = data.model_dump(exclude_unset=True)  # type: ignore[attr-defined]
    if not actor.is_platform_admin:
        values.pop("status", None)
        values.pop("is_demo", None)
        values.pop("slug", None)
    changes = apply_values(TENANT_SPEC, tenant, values)
    if changes:
        audit.record(
            db,
            actor,
            tenant_id=tid,
            entity="tenant",
            entity_id=tid,
            action="update",
            old={k: v[0] for k, v in changes.items()},
            new={k: v[1] for k, v in changes.items()},
            undoable=True,
        )
    return tenant


# ------------------------------------------------------------------ users


class UserIn(BaseModel):
    name: str
    email: str | None = None
    role: str = "dispatcher"
    password: str | None = Field(default=None, min_length=10)
    staff_member_id: uuid.UUID | None = None


class UserPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None
    extra_permissions: list[str] | None = None
    revoked_permissions: list[str] | None = None
    password: str | None = Field(default=None, min_length=10)
    staff_member_id: uuid.UUID | None = None


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{4,8}$")


def user_dict(u: User) -> dict[str, Any]:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "extra_permissions": u.extra_permissions,
        "revoked_permissions": u.revoked_permissions,
        "totp_enabled": u.totp_enabled,
        "staff_member_id": u.staff_member_id,
        "has_pin": bool(u.pin_hash),
        "last_login_at": u.last_login_at,
        "tenant_id": u.tenant_id,
    }


def _tenant_roles(actor: Actor) -> set[str]:
    return {"owner", "dispatcher", "driver"} if actor.role in ("owner", "admin") else {"dispatcher", "driver"}


def _get_user(db: Session, actor: Actor, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.deleted_at is not None:
        raise NotFound()
    if actor.tenant_id is not None and user.tenant_id != actor.tenant_id:
        raise NotFound()
    if actor.tenant_id is None and not actor.is_platform_admin:
        raise NotFound()
    return user


@router.get("/api/users")
def list_users(actor: CurrentActor, db: DB) -> list[dict[str, Any]]:
    actor.require("tenant.users")
    tid = actor.tenant_id
    stmt = select(User).where(User.deleted_at.is_(None))
    stmt = stmt.where(User.tenant_id == tid) if tid else stmt.where(User.tenant_id.is_(None))
    return [user_dict(u) for u in db.scalars(stmt.order_by(User.name))]


@router.post("/api/users", status_code=201)
def add_user(data: UserIn, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.users")
    if actor.tenant_id is None:
        actor.require("platform.tenants")
        role = "admin"
    else:
        role = data.role
        if role not in _tenant_roles(actor):
            raise Forbidden()
    return user_dict(
        create_user(
            db, actor, actor.tenant_id, data.name, data.email, role, data.password, data.staff_member_id
        )
    )


@router.patch("/api/users/{user_id}")
def patch_user(user_id: uuid.UUID, data: UserPatch, actor: CurrentActor, db: DB) -> dict[str, Any]:
    actor.require("tenant.users")
    user = _get_user(db, actor, user_id)
    old = user_dict(user)
    values = data.model_dump(exclude_unset=True)
    if "role" in values and actor.tenant_id is not None and values["role"] not in _tenant_roles(actor):
        raise Forbidden()
    if "role" in values and actor.tenant_id is None:
        values.pop("role")
    for key in ("extra_permissions", "revoked_permissions"):
        if key in values:
            values[key] = [p for p in values[key] if p in ALL_PERMISSIONS]
            if actor.tenant_id is not None:
                values[key] = [p for p in values[key] if not p.startswith("platform.")]
    if "password" in values:
        pw = values.pop("password")
        if pw:
            user.password_hash = hash_password(pw)
    for k, v in values.items():
        setattr(user, k, v)
    new = user_dict(user)
    diff_old = {k: old[k] for k in new if old[k] != new[k]}
    audit.record(
        db,
        actor,
        tenant_id=user.tenant_id,
        entity="user",
        entity_id=user.id,
        action="update",
        old=diff_old,
        new={k: new[k] for k in diff_old},
    )
    return new


@router.delete("/api/users/{user_id}")
def delete_user(user_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict:
    actor.require("tenant.users")
    from app.agents.confirm import confirm_if_agent

    confirm_if_agent(db, actor, "delete:user", {"id": str(user_id)})
    user = _get_user(db, actor, user_id)
    if user.id == actor.user_id:
        raise AppError("errors.forbidden")
    user.deleted_at = datetime.now(UTC)
    user.is_active = False
    user.email = None
    audit.record(db, actor, tenant_id=user.tenant_id, entity="user", entity_id=user.id, action="delete")
    return {"ok": True}


@router.post("/api/users/{user_id}/pin")
def set_pin(user_id: uuid.UUID, data: PinIn, actor: CurrentActor, db: DB) -> dict:
    actor.require("tenant.users")
    user = _get_user(db, actor, user_id)
    tenant = db.get(Tenant, user.tenant_id)
    if tenant is None:
        raise NotFound()
    lookup = pin_lookup(tenant.slug, data.pin)
    clash = db.scalar(select(User).where(User.pin_lookup == lookup, User.id != user.id))
    if clash is not None:
        raise Conflict("errors.pin_taken")
    user.pin_hash = hash_password(data.pin)
    user.pin_lookup = lookup
    audit.record(db, actor, tenant_id=user.tenant_id, entity="user", entity_id=user.id, action="set_pin")
    return {"ok": True, "tenant_code": tenant.slug}


@router.post("/api/users/{user_id}/driver-link")
def driver_link(user_id: uuid.UUID, actor: CurrentActor, db: DB) -> dict:
    """Creates a personal login link for the driver app (valid 30 days, usable on several devices)."""
    actor.require("tenant.users")
    user = _get_user(db, actor, user_id)
    code = new_token(24)
    db.add(
        OneTimeCode(
            tenant_id=user.tenant_id,
            purpose="driver_link",
            code_hash=token_hash(code),
            user_id=user.id,
            created_by=actor.user_id,
            expires_at=datetime.now(UTC) + timedelta(days=30),
            reusable=True,
        )
    )
    audit.record(db, actor, tenant_id=user.tenant_id, entity="user", entity_id=user.id, action="driver_link")
    return {"url": f"{get_config().base_url}/fahrer/login/{code}", "code": code}


@router.get("/api/meta/permissions")
def permissions_meta(actor: CurrentActor) -> dict[str, Any]:
    from app.i18n import catalog

    labels = catalog().get("permissions", {})
    return {
        "permissions": [{"key": p, "label": labels.get(p, p)} for p in ALL_PERMISSIONS],
        "roles": {r: sorted(p) for r, p in ROLE_PERMISSIONS.items()},
    }
