"""Demo data generator – never real customer data.

`python -m app.demo --reset` (re)creates demo tenants with users and, from phase 2 on, staff,
vehicles, equipment, customers, orders, plants, access paths and synthetic measurements.
Every random choice comes from one seeded generator, so runs are reproducible.
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import system_actor
from app.core.db import RlsContext, session_scope, system_session
from app.core.security import hash_password
from app.models.core import Tenant, User

DEMO_PASSWORD = "demo-passwort-2026"

# Two nurseries around Stuttgart (coordinates of the depot are invented but plausible).
DEMO_TENANTS = [
    {
        "slug": "gruenfink",
        "name": "Gärtnerei Grünfink",
        "legal_name": "Gärtnerei Grünfink GmbH",
        "street": "Am Lindenhof 12",
        "postal_code": "70597",
        "city": "Stuttgart",
        "depot_lat": 48.7340,
        "depot_lon": 9.1890,
        "email": "info@gruenfink.example",
        "phone": "0711 000000",
        "owner": ("Henrike Grünfink", "inhaberin@gruenfink.example"),
        "dispatcher": ("Jonas Weber", "dispo@gruenfink.example"),
        "region": {"lat": 48.75, "lon": 9.17, "radius_km": 22},
    },
    {
        "slug": "lindenhof",
        "name": "Baumschule Lindenhof",
        "legal_name": "Baumschule Lindenhof e. K.",
        "street": "Weinbergweg 3",
        "postal_code": "73728",
        "city": "Esslingen am Neckar",
        "depot_lat": 48.7470,
        "depot_lon": 9.3220,
        "email": "kontakt@lindenhof.example",
        "phone": "0711 111111",
        "owner": ("Matthias Lindner", "inhaber@lindenhof.example"),
        "dispatcher": ("Selin Arslan", "dispo@lindenhof.example"),
        "region": {"lat": 48.74, "lon": 9.31, "radius_km": 18},
    },
]


@dataclass
class DemoOptions:
    seed: int = 2026
    orders_per_tenant: int = 100
    staff_per_tenant: int = 10
    measurements: bool = True
    returns: bool = True
    tenants: list[dict[str, Any]] = field(default_factory=lambda: list(DEMO_TENANTS))


# Phase modules register further steps: fn(db, tenant, rng, options, report)
STEPS: list = []


def step(fn):
    STEPS.append(fn)
    return fn


def remove_demo_tenants(db: Session) -> int:
    rows = list(db.scalars(select(Tenant).where(Tenant.is_demo.is_(True))))
    for t in rows:
        db.delete(t)
    # users of deleted tenants are removed by ON DELETE CASCADE
    db.flush()
    return len(rows)


def create_tenant(db: Session, spec: dict[str, Any]) -> Tenant:
    values = {k: v for k, v in spec.items() if k not in ("owner", "dispatcher", "region")}
    tenant = Tenant(**values, is_demo=True, country="DE", status="active")
    db.add(tenant)
    db.flush()
    for role, (name, email) in (("owner", spec["owner"]), ("dispatcher", spec["dispatcher"])):
        existing = db.scalar(select(User).where(User.email == email))
        if existing is not None:
            db.delete(existing)
            db.flush()
        db.add(
            User(
                tenant_id=tenant.id,
                email=email,
                name=name,
                role=role,
                password_hash=hash_password(DEMO_PASSWORD),
                extra_permissions=[],
                revoked_permissions=[],
            )
        )
    db.flush()
    return tenant


def generate(options: DemoOptions | None = None, reset: bool = True) -> dict[str, Any]:
    from app.demo import loaders  # noqa: F401  (registers the steps of all phases)

    options = options or DemoOptions()
    rng = random.Random(options.seed)
    report: dict[str, Any] = {"tenants": []}
    with system_session() as db:
        from app.ai.bootstrap import seed_ai
        from app.demo.species_catalog import seed_species

        seed_ai(db)
        seed_species(db)
        from app.formula.defaults import seed_formulas

        seed_formulas(db)
        if reset:
            report["removed"] = remove_demo_tenants(db)
        created = [create_tenant(db, spec) for spec in options.tenants]
        tenant_ids = [(t.id, spec) for t, spec in zip(created, options.tenants, strict=True)]
    for tenant_id, spec in tenant_ids:
        entry: dict[str, Any] = {"id": str(tenant_id), "name": spec["name"], "slug": spec["slug"]}
        with session_scope(RlsContext(tenant_id=tenant_id)) as db:
            tenant = db.get(Tenant, tenant_id)
            for fn in STEPS:
                fn(db, tenant, rng, options, entry, spec)
        report["tenants"].append(entry)
    report["login"] = {
        "password": DEMO_PASSWORD,
        "accounts": [s["owner"][1] for s in options.tenants] + [s["dispatcher"][1] for s in options.tenants],
    }
    return report


def demo_actor(tenant_id: uuid.UUID):
    return system_actor(tenant_id, label="Demodaten")
