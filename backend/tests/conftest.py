"""Test setup: fresh schema in the test database, migrated with Alembic, app role for queries."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.core.config import get_config

BACKEND = Path(__file__).resolve().parents[1]


def _reset_schema() -> None:
    cfg = get_config()
    if not cfg.test_database_owner_url or not cfg.test_database_url:
        pytest.exit("KP_TEST_DATABASE_URL and KP_TEST_DATABASE_OWNER_URL must be set (.env)")
    engine = create_engine(cfg.test_database_owner_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    os.environ["KP_MIGRATION_URL"] = cfg.test_database_owner_url
    os.environ["KP_APP_URL"] = cfg.test_database_url
    from alembic import command
    from alembic.config import Config as AlembicConfig

    acfg = AlembicConfig(str(BACKEND / "alembic.ini"))
    acfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(acfg, "head")


@pytest.fixture(scope="session", autouse=True)
def test_database():
    _reset_schema()
    from app.core.db import configure_engine

    configure_engine(get_config().test_database_url)
    yield


class Api:
    """TestClient wrapper that sends the CSRF header automatically and raises on unexpected status."""

    def __init__(self, client) -> None:
        self.c = client

    def _headers(self, headers):
        h = dict(headers or {})
        csrf = self.c.cookies.get("kp_csrf")
        if csrf:
            h.setdefault("X-CSRF-Token", csrf)
        return h

    def req(self, method: str, url: str, expect: int | None = 200, headers=None, **kw):
        r = self.c.request(method, url, headers=self._headers(headers), **kw)
        if expect is not None and r.status_code != expect:
            raise AssertionError(f"{method} {url} -> {r.status_code}: {r.text[:800]}")
        return r

    def get(self, url, expect=200, **kw):
        return self.req("GET", url, expect, **kw)

    def post(self, url, expect=200, **kw):
        return self.req("POST", url, expect, **kw)

    def put(self, url, expect=200, **kw):
        return self.req("PUT", url, expect, **kw)

    def patch(self, url, expect=200, **kw):
        return self.req("PATCH", url, expect, **kw)

    def delete(self, url, expect=200, **kw):
        return self.req("DELETE", url, expect, **kw)

    def login(self, email: str, password: str, **kw):
        return self.post("/api/auth/login", json={"email": email, "password": password, **kw})


@pytest.fixture(scope="session")
def app():
    from app.main import create_app

    return create_app()


@pytest.fixture
def make_client(app):
    from fastapi.testclient import TestClient

    clients = []

    def _make() -> Api:
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        return Api(c)

    yield _make
    for c in clients:
        c.__exit__(None, None, None)


@pytest.fixture
def admin(make_client) -> Api:
    api = make_client()
    cfg = get_config()
    api.login(cfg.initial_admin_email, cfg.initial_admin_password)
    return api


@pytest.fixture
def new_tenant(admin, make_client):
    """Factory: creates a tenant with an owner and returns (tenant_json, logged-in owner Api)."""

    def _make(name: str | None = None):
        name = name or f"Gärtnerei {uuid.uuid4().hex[:6]}"
        email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
        r = admin.post(
            "/api/admin/tenants",
            expect=201,
            json={
                "tenant": {"name": name, "city": "Stuttgart", "depot_lat": 48.78, "depot_lon": 9.18},
                "owner": {"name": "Inhaber", "email": email, "password": "geheim-123456"},
            },
        )
        owner = make_client()
        owner.login(email, "geheim-123456")
        return r.json(), owner

    return _make
