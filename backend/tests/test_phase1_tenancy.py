"""Tenant isolation (API and row-level security), authentication, roles, jobs."""

from __future__ import annotations

import uuid

import pyotp
import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.db import RlsContext, session_scope, system_session
from app.models.core import AuditLog, SettingValue, Tenant, User


def test_two_tenants_see_only_own_data(admin, new_tenant):
    ta, owner_a = new_tenant("Gärtnerei Anton")
    tb, owner_b = new_tenant("Gärtnerei Berta")

    owner_a.post(
        "/api/users",
        expect=201,
        json={
            "name": "Disponentin A",
            "email": f"a-{uuid.uuid4().hex[:6]}@ex.com",
            "role": "dispatcher",
            "password": "geheim-123456",
        },
    )
    owner_a.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 33})
    owner_b.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 44})

    users_a = owner_a.get("/api/users").json()
    users_b = owner_b.get("/api/users").json()
    assert {u["tenant_id"] for u in users_a} == {ta["id"]}
    assert {u["tenant_id"] for u in users_b} == {tb["id"]}
    assert len(users_a) == 2 and len(users_b) == 1

    assert owner_a.get("/api/tenant").json()["name"] == "Gärtnerei Anton"
    # B cannot address A's settings or users
    owner_b.get("/api/settings", params={"tenant_id": ta["id"]}, expect=403)
    owner_b.patch(f"/api/users/{users_a[0]['id']}", json={"name": "x"}, expect=404)
    # audit logs are separated
    assert all(e["tenant_id"] == tb["id"] for e in owner_b.get("/api/audit").json()["items"])
    # tenants cannot use admin endpoints
    owner_a.get("/api/admin/tenants", expect=403)
    # admin sees both
    names = {t["name"] for t in admin.get("/api/admin/tenants").json()}
    assert {"Gärtnerei Anton", "Gärtnerei Berta"} <= names


def test_row_level_security_without_application_filter(new_tenant):
    """Even a query without any tenant filter only returns the current tenant's rows."""
    ta, _ = new_tenant()
    tb, _ = new_tenant()
    a, b = uuid.UUID(ta["id"]), uuid.UUID(tb["id"])
    with session_scope(RlsContext(tenant_id=a)) as db:
        tenants = db.scalars(select(Tenant)).all()
        assert [t.id for t in tenants] == [a]
        assert {u.tenant_id for u in db.scalars(select(User))} == {a}
        assert all(e.tenant_id == a for e in db.scalars(select(AuditLog)))
        # writing a row for another tenant is rejected by the policy
        db.add(SettingValue(scope="tenant", tenant_id=b, key="pricing.base_price", value=1))
        with pytest.raises(DBAPIError):
            db.flush()
        db.rollback()
    with session_scope(RlsContext()) as db:  # no tenant, no bypass: nothing visible
        assert db.scalars(select(Tenant)).all() == []
        assert db.scalars(select(User)).all() == []
    with system_session() as db:
        assert db.scalar(text("SELECT current_user")) != "kp_owner"
        assert (
            db.scalar(text("SELECT rolbypassrls OR rolsuper FROM pg_roles WHERE rolname = current_user"))
            is False
        )


def test_global_rows_read_only_for_tenants(admin, new_tenant):
    _, owner = new_tenant()
    admin.put("/api/settings", json={"scope": "platform", "key": "costs.fuel_price", "value": 1.9})
    tid = uuid.UUID(owner.get("/api/tenant").json()["id"])
    with session_scope(RlsContext(tenant_id=tid)) as db:
        row = db.scalar(
            select(SettingValue).where(
                SettingValue.scope == "platform", SettingValue.key == "costs.fuel_price"
            )
        )
        assert row is not None  # readable
        db.execute(text("DELETE FROM setting_values WHERE scope = 'platform'"))
        db.flush()
    with system_session() as db:
        assert db.scalar(
            select(SettingValue).where(
                SettingValue.scope == "platform", SettingValue.key == "costs.fuel_price"
            )
        )
    admin.post("/api/settings/reset", json={"scope": "platform", "key": "costs.fuel_price"})


def test_login_rate_limit_and_csrf(make_client, new_tenant):
    api = make_client()
    email = f"rl-{uuid.uuid4().hex[:6]}@example.com"
    for _ in range(8):
        api.post("/api/auth/login", json={"email": email, "password": "falsch"}, expect=401)
    r = api.post("/api/auth/login", json={"email": email, "password": "falsch"}, expect=429)
    assert r.json()["error"]["code"] == "errors.login_rate_limited"

    _, owner = new_tenant()
    r = owner.c.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 1})
    assert r.status_code == 403 and r.json()["error"]["code"] == "errors.csrf"


def test_dispatcher_permissions(new_tenant, make_client):
    _, owner = new_tenant()
    email = f"d-{uuid.uuid4().hex[:6]}@example.com"
    u = owner.post(
        "/api/users",
        expect=201,
        json={"name": "Dispo", "email": email, "role": "dispatcher", "password": "geheim-123456"},
    ).json()
    dispo = make_client()
    dispo.login(email, "geheim-123456")
    dispo.get("/api/users", expect=403)  # no user management
    dispo.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 50})
    # fine-grained: revoke tenant.settings
    owner.patch(f"/api/users/{u['id']}", json={"revoked_permissions": ["tenant.settings"]})
    dispo.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 51}, expect=403)
    # owner cannot grant platform permissions
    owner.patch(f"/api/users/{u['id']}", json={"extra_permissions": ["platform.tenants"]})
    assert "platform.tenants" not in dispo.get("/api/auth/me").json()["permissions"]


def test_two_factor_required_for_admin(admin, make_client):
    email = f"admin2-{uuid.uuid4().hex[:6]}@example.com"
    admin.post(
        "/api/users", expect=201, json={"name": "Admin 2", "email": email, "password": "geheim-123456"}
    )
    admin.put("/api/settings", json={"scope": "platform", "key": "security.admin_require_2fa", "value": True})
    try:
        a2 = make_client()
        assert a2.login(email, "geheim-123456").json()["mfa_setup_required"] is True
        a2.get("/api/admin/tenants", expect=403)
        secret = a2.post("/api/auth/2fa/setup").json()["secret"]
        a2.post("/api/auth/2fa/enable", json={"code": pyotp.TOTP(secret).now()})
        a2.get("/api/admin/tenants")
        a3 = make_client()
        r = a3.post("/api/auth/login", json={"email": email, "password": "geheim-123456"}, expect=401)
        assert r.json()["error"]["code"] == "errors.mfa_required"
        a3.login(email, "geheim-123456", code=pyotp.TOTP(secret).now())
    finally:
        admin.put(
            "/api/settings", json={"scope": "platform", "key": "security.admin_require_2fa", "value": False}
        )


def test_driver_pin_and_link(new_tenant, make_client):
    t, owner = new_tenant()
    d = owner.post("/api/users", expect=201, json={"name": "Fahrer Paul", "role": "driver"}).json()
    owner.post(f"/api/users/{d['id']}/pin", json={"pin": "4711"})
    drv = make_client()
    drv.post("/api/auth/driver/pin", json={"tenant": t["slug"], "pin": "4711"})
    me = drv.get("/api/auth/me").json()
    assert me["role"] == "driver" and me["permissions"] == ["driver.app"]
    drv.get("/api/users", expect=403)
    link = owner.post(f"/api/users/{d['id']}/driver-link").json()
    drv2 = make_client()
    drv2.post(f"/api/auth/link/{link['code']}")
    assert drv2.get("/api/auth/me").json()["user"]["name"] == "Fahrer Paul"


def test_admin_act_as_tenant(admin, new_tenant):
    t, _ = new_tenant()
    admin.post("/api/auth/act-as", json={"tenant_id": t["id"]})
    assert admin.get("/api/tenant").json()["id"] == t["id"]
    admin.put("/api/settings", json={"scope": "tenant", "key": "pricing.base_price", "value": 12})
    admin.post("/api/auth/act-as", json={"tenant_id": None})
    vals = admin.get("/api/settings", params={"tenant_id": t["id"]}).json()["values"]
    assert next(v for v in vals if v["key"] == "pricing.base_price")["value"] == 12


def test_jobs_progress(new_tenant):
    from app.core.db import tenant_session
    from app.jobs.queue import enqueue, run_pending

    t, owner = new_tenant()
    with tenant_session(uuid.UUID(t["id"])) as db:
        job = enqueue(db, "system.echo", {"steps": 2}, tenant_id=uuid.UUID(t["id"]))
        job_id = job.id
    run_pending()
    j = owner.get(f"/api/jobs/{job_id}").json()
    assert j["status"] == "done" and j["progress"] == 1.0 and j["result"]["echo"]["steps"] == 2
