"""Who is acting: the authenticated user, agent token or system process."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from app.core.db import RlsContext
from app.core.errors import Forbidden


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID | None
    label: str
    role: str
    tenant_id: uuid.UUID | None
    permissions: frozenset[str] = field(default_factory=frozenset)
    via: str = "ui"  # ui | api | agent | settings_ai | system
    agent_token_id: uuid.UUID | None = None
    staff_member_id: uuid.UUID | None = None
    confirmation_id: str | None = None  # agents: approved confirmation sent with X-KP-Confirmation

    @property
    def is_platform_admin(self) -> bool:
        """Platform admin or an internal system process."""
        return self.role in ("admin", "system")

    def has(self, perm: str) -> bool:
        return perm in self.permissions

    def require(self, *perms: str) -> None:
        for p in perms:
            if p not in self.permissions:
                raise Forbidden("errors.missing_permission", permission=p)

    def require_tenant(self) -> uuid.UUID:
        if self.tenant_id is None:
            raise Forbidden("errors.tenant_required")
        return self.tenant_id

    def with_via(self, via: str) -> Actor:
        return replace(self, via=via)

    @property
    def rls(self) -> RlsContext:
        if self.tenant_id is not None:
            return RlsContext(tenant_id=self.tenant_id)
        if self.is_platform_admin or self.role == "system":
            return RlsContext(bypass=True)
        return RlsContext()


def system_actor(tenant_id: uuid.UUID | None = None, label: str = "System") -> Actor:
    from app.core.permissions import ALL_PERMISSIONS

    return Actor(
        user_id=None,
        label=label,
        role="system",
        tenant_id=tenant_id,
        permissions=frozenset(ALL_PERMISSIONS),
        via="system",
    )
