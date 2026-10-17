"""Roles and fine-grained permissions.

A user's effective permissions = role defaults + extra_permissions - revoked_permissions.
New roles only need an entry in ROLE_PERMISSIONS.
"""

from __future__ import annotations

ALL_PERMISSIONS: tuple[str, ...] = (
    # platform
    "platform.tenants",
    "platform.settings",
    "platform.formulas",
    "platform.species",
    "platform.ai",
    "platform.billing",
    "platform.agents",
    "platform.system",
    # tenant
    "tenant.view",
    "tenant.profile",
    "tenant.users",
    "tenant.settings",
    "tenant.billing",
    "tenant.agents",
    "staff.read",
    "staff.write",
    "fleet.read",
    "fleet.write",
    "customers.read",
    "customers.write",
    "orders.read",
    "orders.write",
    "drafts.write",
    "species.write",
    "formulas.write",
    "pricing.write",
    "planning.read",
    "planning.write",
    "scenarios.run",
    "model.fit",
    "ai.use",
    "audit.read",
    # driver
    "driver.app",
    # customer (later)
    "customer.portal",
)

_TENANT_ALL = tuple(p for p in ALL_PERMISSIONS if not p.startswith(("platform.", "driver.", "customer.")))

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": frozenset(ALL_PERMISSIONS),
    "owner": frozenset(_TENANT_ALL),
    "dispatcher": frozenset(
        p for p in _TENANT_ALL if p not in ("tenant.billing", "tenant.users", "tenant.agents")
    ),
    "driver": frozenset({"driver.app"}),
    "customer": frozenset({"customer.portal"}),
}

# Scopes an agent token can carry, mapped to permissions they unlock.
AGENT_SCOPES: dict[str, frozenset[str]] = {
    "read": frozenset(
        p for p in _TENANT_ALL if p.endswith((".read", ".view")) or p in ("tenant.view", "audit.read")
    ),
    "drafts": frozenset({"drafts.write", "orders.read", "customers.read", "tenant.view"}),
    "masterdata": frozenset(
        {"staff.write", "fleet.write", "customers.write", "orders.write", "species.write"}
    ),
    "planning": frozenset({"planning.read", "planning.write", "scenarios.run", "model.fit"}),
    "settings": frozenset({"tenant.settings", "formulas.write", "pricing.write"}),
    "admin_support": frozenset(
        {"platform.system", "platform.settings", "platform.species", "platform.formulas", "platform.ai"}
    ),
    "admin_full": frozenset(ALL_PERMISSIONS),
}


def effective_permissions(role: str, extra: list[str] | None, revoked: list[str] | None) -> frozenset[str]:
    perms = set(ROLE_PERMISSIONS.get(role, frozenset()))
    perms |= {p for p in (extra or []) if p in ALL_PERMISSIONS}
    perms -= set(revoked or [])
    return frozenset(perms)
