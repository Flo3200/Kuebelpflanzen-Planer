"""Optional modules of a tenant (settings ``modules.*``).

The platform focuses on logistics (pickup, tours, loading, unloading, return). Storage, prices with
quotes and invoices to end customers, the customer portal and online payment are modules that are
off by default. A module that is off disappears from menu, dashboard and forms, and its endpoints
answer 409 ``errors.module_off``. Tables and data stay untouched, so switching back on restores
everything.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import AppError

MODULES: tuple[str, ...] = ("storage", "customer_billing", "portal", "payments", "share")
# a module only works if the modules it builds on are on as well
REQUIRES: dict[str, tuple[str, ...]] = {"payments": ("portal",)}


def module_states(resolver) -> dict[str, bool]:
    """Effective state of every module for the resolver's tenant (dependencies applied)."""
    raw = {m: bool(resolver.get(f"modules.{m}")) for m in MODULES}
    return {m: raw[m] and all(raw[d] for d in REQUIRES.get(m, ())) for m in MODULES}


def module_enabled(db: Session, tenant_id: uuid.UUID | None, name: str, resolver=None) -> bool:
    if tenant_id is None:
        return True  # platform view (admin) sees everything
    if resolver is None:
        from app.settings.service import SettingsResolver

        resolver = SettingsResolver(db, tenant_id)
    return module_states(resolver)[name]


def require_module(db: Session, tenant_id: uuid.UUID | None, name: str, resolver=None) -> None:
    if not module_enabled(db, tenant_id, name, resolver):
        raise AppError("errors.module_off", status_code=409, module=name)
