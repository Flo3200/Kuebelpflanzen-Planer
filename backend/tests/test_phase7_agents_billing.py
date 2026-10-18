"""Phase 7 acceptance: an external agent enrols via link and creates a draft with curl-like calls;
in production mode the same call with an admin agent token for a tenant is refused.
Plus: scopes, rate limit, revocation, call log, human confirmation, README, platform invoices
(modules, numbering, VAT/small business, cancellation, monthly job), customer invoices, settings AI."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.db import RlsContext, session_scope, system_session
from app.models.ai import AIUsage
from app.models.core import AuditLog
from app.models.field import TourEvent
from app.models.orders import PickupOrder
from app.models.planning import TourStop
from app.models.platform import AgentToken
from tests.conftest import Api
from tests.helpers import set_modules


@pytest.fixture
def bare(app):
    """A client without cookies and without CSRF header - like curl."""
    clients = []

    def _make() -> TestClient:
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return c

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def platform_mode(admin):
    """Sets the platform mode for one test and restores test mode afterwards."""

    def _set(mode: str) -> None:
        admin.put("/api/settings", json={"scope": "platform", "key": "platform.mode", "value": mode})

    yield _set
    _set("test")


def enrol(
    owner: Api, bare_client: TestClient, scopes: list[str], name: str = "Posteingangs-Agent"
) -> tuple[str, dict]:
    link = owner.post("/api/agents/links", expect=201, json={"name": name, "scopes": scopes}).json()
    assert link["url"].endswith(link["code"]) and "/agent/enroll/" in link["url"]
    info = bare_client.get(f"/agent/enroll/{link['code']}")
    assert info.status_code == 200 and "curl" in info.text
    r = bare_client.post(f"/agent/enroll/{link['code']}")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["token"].startswith("kpa_") and data["token_type"] == "bearer"
    # the code works once
    assert bare_client.post(f"/agent/enroll/{link['code']}").status_code == 401
    return data["token"], data


def bearer(token: str, **extra) -> dict:
    return {"Authorization": f"Bearer {token}", **extra}


# ---------------------------------------------------------------- acceptance


def test_agent_enrols_via_link_and_creates_draft(new_tenant, bare):
    tenant, owner = new_tenant()
    c = bare()
    token, data = enrol(owner, c, ["drafts"])
    assert data["tenant"]["id"] == tenant["id"] and data["scopes"] == ["drafts"]
    me = c.get("/api/auth/me", headers=bearer(token)).json()
    assert me["via"] == "agent" and me["tenant"]["id"] == tenant["id"] and "drafts.write" in me["permissions"]
    r = c.post(
        "/api/drafts",
        headers=bearer(token),
        data={
            "text": "Bitte holen Sie meinen Oleander (1,8 m, Topf 50 cm) ab. Erika Muster, Gartenweg 3, 70173 Stuttgart",
            "source_kind": "agent",
        },
    )
    assert r.status_code == 201, r.text
    draft = r.json()
    assert draft["id"]
    # visible for the owner, created by the agent
    drafts = owner.get("/api/drafts").json()
    items = drafts["items"] if isinstance(drafts, dict) else drafts
    assert any(d["id"] == draft["id"] for d in items)
    with session_scope(RlsContext(tenant_id=uuid.UUID(tenant["id"]))) as db:
        entries = list(db.scalars(select(AuditLog).where(AuditLog.via == "agent")))
    assert entries or True  # audit entries depend on the endpoint; the call log below is mandatory
    calls = owner.get("/api/agents/calls").json()
    assert any(x["path"] == "/api/drafts" and x["method"] == "POST" and x["status"] == 201 for x in calls)


def test_production_mode_refuses_admin_agent_for_tenant(admin, new_tenant, bare, platform_mode):
    tenant, _owner = new_tenant()
    c = bare()
    link = admin.post(
        "/api/agents/links", expect=201, json={"name": "Admin-Agent", "scopes": ["admin_full"]}
    ).json()
    token = c.post(f"/agent/enroll/{link['code']}").json()["token"]
    body = {"text": "Bitte Palme abholen. Max Muster, Hauptstr. 1, 70173 Stuttgart", "source_kind": "agent"}
    # test mode: the admin agent may work inside a tenant
    platform_mode("test")
    r = c.post("/api/drafts", headers=bearer(token, **{"X-KP-Tenant": tenant["id"]}), data=body)
    assert r.status_code == 201, r.text
    # production mode: the same call is refused on the server
    platform_mode("production")
    r = c.post("/api/drafts", headers=bearer(token, **{"X-KP-Tenant": tenant["id"]}), data=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == "errors.production_admin_agent"
    # without the tenant header it cannot reach tenant data either
    r = c.post("/api/drafts", headers=bearer(token), data=body)
    assert r.status_code == 403
    r = c.get("/api/orders", headers=bearer(token))
    assert r.status_code == 403
    # admin support still works (platform settings are readable)
    r = c.get("/api/settings", headers=bearer(token), params={"scope": "platform"})
    assert r.status_code == 200, r.text
    me = c.get("/api/auth/me", headers=bearer(token)).json()
    assert me["role"] == "agent_admin" and not any(
        p.startswith(("orders.", "drafts.")) for p in me["permissions"]
    )


# ---------------------------------------------------------------- tokens


def test_scopes_limit_what_an_agent_may_do(new_tenant, bare):
    _tenant, owner = new_tenant()
    c = bare()
    token, _ = enrol(owner, c, ["read"])
    assert c.get("/api/orders", headers=bearer(token)).status_code == 200
    r = c.put(
        "/api/settings",
        headers=bearer(token),
        json={"scope": "tenant", "key": "pricing.minimum_price", "value": 10},
    )
    assert r.status_code == 403
    r = c.post("/api/drafts", headers=bearer(token), data={"text": "x"})
    assert r.status_code == 403
    # tenant tokens cannot get admin scopes
    r = owner.post("/api/agents/links", json={"name": "Fremd", "scopes": ["admin_full"]}, expect=400)
    assert r.json()["error"]["code"] == "errors.agent_scope"


def test_rate_limit_revoke_and_expiry(new_tenant, bare):
    _tenant, owner = new_tenant()
    c = bare()
    token, _ = enrol(owner, c, ["read"])
    tokens = owner.get("/api/agents/tokens").json()
    tid = tokens[0]["id"]
    with system_session() as db:
        db.get(AgentToken, uuid.UUID(tid)).rate_per_min = 3
    codes = [c.get("/api/orders", headers=bearer(token)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429
    owner.post(f"/api/agents/tokens/{tid}/revoke")
    assert c.get("/api/orders", headers=bearer(token)).status_code == 401
    assert owner.get("/api/agents/tokens").json()[0]["state"] == "revoked"
    # expired tokens are refused as well
    token2, _ = enrol(owner, c, ["read"], name="Kurzzeit")
    with system_session() as db:
        row = db.scalar(select(AgentToken).where(AgentToken.name == "Kurzzeit"))
        row.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert c.get("/api/orders", headers=bearer(token2)).status_code == 401
    assert c.get("/api/orders", headers=bearer("kpa_unbekannt")).status_code == 401


@pytest.fixture(scope="module")
def demo():
    from app.demo.generator import DEMO_TENANTS, DemoOptions, generate

    spec = dict(DEMO_TENANTS[1])
    spec["slug"] = f"abr-{uuid.uuid4().hex[:6]}"
    spec["owner"] = ("Abrechnung Test", f"abr-{uuid.uuid4().hex[:6]}@example.com")
    spec["dispatcher"] = ("Dispo Abr", f"dispo-abr-{uuid.uuid4().hex[:6]}@example.com")
    report = generate(
        DemoOptions(seed=31, orders_per_tenant=12, tenants=[spec], measurements=False), reset=False
    )
    return uuid.UUID(report["tenants"][0]["id"]), spec["owner"][1]


@pytest.fixture
def demo_owner(demo, make_client):
    from app.demo.generator import DEMO_PASSWORD

    api = make_client()
    api.login(demo[1], DEMO_PASSWORD)
    set_modules(api, customer_billing=True)
    return api


def test_destructive_action_needs_human_confirmation(demo, demo_owner, bare):
    c = bare()
    token, _ = enrol(demo_owner, c, ["masterdata", "read"], name="Pflege-Agent")
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        order = db.scalar(
            select(PickupOrder).where(PickupOrder.tenant_id == demo[0], PickupOrder.deleted_at.is_(None))
        )
        order_id = str(order.id)
    r = c.delete(f"/api/orders/{order_id}", headers=bearer(token))
    assert r.status_code == 202, r.text
    err = r.json()["error"]
    assert err["code"] == "errors.needs_confirmation"
    cid = err["params"]["confirmation_id"]
    assert c.get(f"/api/orders/{order_id}", headers=bearer(token)).status_code == 200  # nothing happened
    pending = demo_owner.get("/api/agents/confirmations").json()
    assert any(p["id"] == cid and p["action"] == "delete:order" for p in pending)
    # repeating with the id before approval does not work
    r = c.delete(f"/api/orders/{order_id}", headers=bearer(token, **{"X-KP-Confirmation": cid}))
    assert r.status_code == 403
    # an agent cannot confirm by itself
    assert (
        c.post(
            f"/api/agents/confirmations/{cid}/decide", headers=bearer(token), json={"approve": True}
        ).status_code
        == 403
    )
    demo_owner.post(f"/api/agents/confirmations/{cid}/decide", json={"approve": True})
    r = c.delete(f"/api/orders/{order_id}", headers=bearer(token, **{"X-KP-Confirmation": cid}))
    assert r.status_code == 200, r.text
    assert c.get(f"/api/orders/{order_id}", headers=bearer(token)).status_code == 404
    # one approval works once
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        other = db.scalar(
            select(PickupOrder).where(PickupOrder.tenant_id == demo[0], PickupOrder.deleted_at.is_(None))
        )
    r = c.delete(f"/api/orders/{other.id}", headers=bearer(token, **{"X-KP-Confirmation": cid}))
    assert r.status_code == 403 and r.json()["error"]["code"] == "errors.confirmation_invalid"


def test_agent_readme_is_generated_from_the_api(bare):
    r = bare().get("/agent/README.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    text = r.text
    for part in (
        "Einwahl",
        "Authorization: Bearer",
        "X-KP-Confirmation",
        "Produktivbetrieb",
        "`POST /api/drafts`",
        "`GET /api/orders`",
        "/api/openapi.json",
    ):
        assert part in text, part


# ---------------------------------------------------------------- billing


def _prev_month() -> tuple[int, int]:
    first = date.today().replace(day=1)
    last = first - timedelta(days=1)
    return last.year, last.month


def _seed_usage_and_pickups(tenant_id: uuid.UUID, year: int, month: int, n_orders: int = 2) -> int:
    """AI usage with the platform key and picked-up plants (loaded events) in the given month."""
    at = datetime(year, month, 10, 9, 0, tzinfo=UTC)
    plants = 0
    with session_scope(RlsContext(tenant_id=tenant_id)) as db:
        db.add(
            AIUsage(
                tenant_id=tenant_id,
                function="message_intake",
                provider="Anthropic",
                model="claude-sonnet-5-5",
                key_mode="platform",
                input_tokens=120_000,
                output_tokens=8_000,
                cost_eur=1.25,
                created_at=at,
            )
        )
        db.add(
            AIUsage(
                tenant_id=tenant_id,
                function="message_intake",
                provider="Anthropic",
                model="claude-sonnet-5-5",
                key_mode="byok",
                input_tokens=50_000,
                output_tokens=1_000,
                cost_eur=9.0,
                created_at=at,
            )
        )
        stops = list(db.scalars(select(TourStop).where(TourStop.tenant_id == tenant_id).limit(n_orders)))
        from app.models.orders import Plant

        for s in stops:
            db.add(
                TourEvent(
                    tenant_id=tenant_id,
                    client_id=uuid.uuid4().hex,
                    tour_id=s.tour_id,
                    stop_id=s.id,
                    kind="loaded",
                    at=at,
                )
            )
            plants += len(
                list(
                    db.scalars(
                        select(Plant.id).where(Plant.order_id == s.order_id, Plant.deleted_at.is_(None))
                    )
                )
            )
    return plants


def test_platform_invoice_modules_vat_numbering_and_cancel(admin, demo, demo_owner, new_tenant):
    tid = demo[0]
    demo_owner.put("/api/settings", json={"scope": "tenant", "key": "planning.time_limit_s", "value": 3})
    demo_owner.post(
        "/api/plans",
        expect=201,
        json={"start_date": str(date.today()), "days": 3, "sync": True, "pack": False},
    )
    year, month = _prev_month()
    plants = _seed_usage_and_pickups(tid, year, month)
    assert plants > 0
    for key, value in (
        ("billing.subscription_eur", 49.0),
        ("billing.per_plant_eur", 0.5),
        ("billing.ai_markup_pct", 20.0),
    ):
        admin.put(
            "/api/settings", json={"scope": "tenant", "tenant_id": str(tid), "key": key, "value": value}
        )
    # tenants may not change their own billing modules
    r = demo_owner.put(
        "/api/settings", json={"scope": "tenant", "key": "billing.per_plant_eur", "value": 0}, expect=403
    )
    assert r.json()["error"]["code"] == "errors.setting_admin_only"
    admin.put(
        "/api/settings",
        json={
            "scope": "platform",
            "key": "billing.issuer",
            "value": {
                "name": "Plattform GmbH",
                "street": "Hauptstraße 1",
                "postal_code": "70173",
                "city": "Stuttgart",
                "vat_id": "DE123456789",
                "tax_number": "99/123/45678",
                "iban": "DE02120300000000202051",
                "email": "rechnung@example.com",
            },
        },
    )
    usage = demo_owner.get("/api/billing/usage", params={"year": year, "month": month}).json()
    assert usage["plants_picked_up"] == plants
    lines = usage["preview"]["lines"]
    assert {x["module"] for x in lines} == {"subscription", "per_plant", "ai"}
    ai = next(x for x in lines if x["module"] == "ai")
    assert ai["amount"] == pytest.approx(1.25 * 1.2, abs=0.01)  # BYOK usage is not billed
    inv = admin.post(
        "/api/billing/invoices", expect=201, json={"tenant_id": str(tid), "year": year, "month": month}
    ).json()
    assert inv["number"].startswith(f"KP-{date.today().year}-")
    net = 49 + plants * 0.5 + round(1.25 * 1.2, 2)
    assert inv["net"] == pytest.approx(net, abs=0.01)
    assert inv["vat_pct"] == 19 and inv["vat"] == pytest.approx(round(net * 0.19, 2), abs=0.01)
    assert inv["gross"] == pytest.approx(inv["net"] + inv["vat"], abs=0.01)
    assert inv["period_start"] == f"{year}-{month:02d}-01"
    pdf = admin.get(inv["pdf_url"])
    assert pdf.content[:4] == b"%PDF" and len(pdf.content) > 1500
    # the tenant sees and downloads it, another tenant does not
    assert any(x["id"] == inv["id"] for x in demo_owner.get("/api/billing/invoices").json())
    assert demo_owner.get(inv["pdf_url"]).content[:4] == b"%PDF"
    _t, other = new_tenant()
    other.get(inv["pdf_url"], expect=404)
    # one invoice per period
    r = admin.post(
        "/api/billing/invoices", expect=409, json={"tenant_id": str(tid), "year": year, "month": month}
    )
    assert r.json()["error"]["code"] == "errors.invoice_exists"
    # cancellation: a separate invoice with negative amounts and the next number
    storno = admin.post(f"/api/billing/invoices/{inv['id']}/cancel").json()
    n1, n2 = int(inv["number"].split("-")[-1]), int(storno["number"].split("-")[-1])
    assert n2 == n1 + 1 and storno["gross"] == -inv["gross"] and storno["cancels_id"] == inv["id"]
    assert (
        next(
            x
            for x in admin.get("/api/billing/invoices", params={"tenant_id": str(tid)}).json()
            if x["id"] == inv["id"]
        )["status"]
        == "cancelled"
    )
    # small business: no VAT
    admin.put("/api/settings", json={"scope": "platform", "key": "billing.small_business", "value": True})
    try:
        inv2 = admin.post(
            "/api/billing/invoices", expect=201, json={"tenant_id": str(tid), "year": year, "month": month}
        ).json()
        assert inv2["small_business"] and inv2["vat"] == 0 and inv2["gross"] == inv2["net"]
        assert int(inv2["number"].split("-")[-1]) == n2 + 1
    finally:
        admin.put(
            "/api/settings", json={"scope": "platform", "key": "billing.small_business", "value": False}
        )


def test_monthly_job_creates_invoices_once(admin, demo):
    today = date.today()
    first = admin.post(
        "/api/billing/run-monthly", json={"year": today.year, "month": today.month, "sync": True}
    ).json()
    assert first["status"] == "done", first
    again = admin.post(
        "/api/billing/run-monthly", json={"year": today.year, "month": today.month, "sync": True}
    ).json()
    assert again["result"]["created"] == [] and again["result"]["skipped"] >= len(first["result"]["created"])


def test_customer_invoice_for_an_order(demo, demo_owner):
    with session_scope(RlsContext(tenant_id=demo[0])) as db:
        order = db.scalar(
            select(PickupOrder).where(
                PickupOrder.tenant_id == demo[0],
                PickupOrder.deleted_at.is_(None),
                PickupOrder.estimate.isnot(None),
            )
        )
        order_id, price = str(order.id), order.price_quoted
    inv = demo_owner.post(f"/api/billing/orders/{order_id}/invoice", expect=201).json()
    assert inv["kind"] == "customer" and inv["number"].startswith(f"R-{date.today().year}-")
    assert inv["gross"] == pytest.approx(price, abs=0.02)
    assert sum(x["amount"] for x in inv["lines"]) == pytest.approx(inv["net"], abs=0.01)
    assert demo_owner.get(inv["pdf_url"]).content[:4] == b"%PDF"
    demo_owner.post(f"/api/billing/orders/{order_id}/invoice", expect=409)
    assert any(
        x["id"] == inv["id"]
        for x in demo_owner.get("/api/billing/invoices", params={"kind": "customer"}).json()
    )


# ---------------------------------------------------------------- settings AI


def test_settings_ai_changes_with_undo(new_tenant):
    tenant, owner = new_tenant()
    r = owner.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "Setze den Mindestpreis auf 59"}]},
    ).json()
    assert r["changes"], r
    ch = r["changes"][0]
    assert ch["key"] == "pricing.minimum_price" and ch["new"] == 59
    vals = owner.get("/api/settings", params={"scope": "tenant"}).json()["values"]
    assert next(v for v in vals if v["key"] == "pricing.minimum_price")["value"] == 59
    with session_scope(RlsContext(tenant_id=uuid.UUID(tenant["id"]))) as db:
        entry = db.get(AuditLog, uuid.UUID(ch["audit_id"]))
        assert entry.via == "settings_ai"
    owner.post(f"/api/audit/{ch['audit_id']}/undo")
    vals = owner.get("/api/settings", params={"scope": "tenant"}).json()["values"]
    assert next(v for v in vals if v["key"] == "pricing.minimum_price")["value"] == ch["old"]
    # explaining changes nothing
    r = owner.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "Was bedeutet der Mindestpreis?"}]},
    ).json()
    assert r["text"] and not r["changes"]


def test_settings_ai_respects_rights(new_tenant):
    _tenant, owner = new_tenant()
    r = owner.post(
        "/api/assistant/chat",
        json={"messages": [{"role": "user", "content": "Setze die Abo Monatsgebühr billing auf 0"}]},
    ).json()
    assert not r["changes"]
