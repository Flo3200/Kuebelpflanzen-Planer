"""Human confirmation for destructive or billing-relevant agent actions.

1. The agent calls e.g. DELETE /api/orders/<id>. The server stores a pending confirmation and
   answers 202 with error code errors.needs_confirmation and the confirmation id. Nothing happens.
2. A human approves (or rejects) it in the interface (Agenten -> Bestätigungen).
3. The agent repeats exactly the same request with the header X-KP-Confirmation: <id>.
   The approval fits only this token, this action and these parameters, and works once.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.db import system_session
from app.core.errors import Forbidden, NeedsConfirmation
from app.models.platform import PendingConfirmation

VALID_DAYS = 7


def confirm_if_agent(db: Session, actor: Actor, action: str, payload: dict[str, Any]) -> None:
    """Returns if the action may run now; raises NeedsConfirmation (202) for an agent without approval."""
    if actor.via != "agent":
        return
    now = datetime.now(UTC)
    if actor.confirmation_id:
        with system_session() as sdb:
            try:
                pc = sdb.get(PendingConfirmation, uuid.UUID(actor.confirmation_id))
            except ValueError:
                pc = None
            valid = (
                pc is not None
                and pc.status == "approved"
                and pc.token_id == actor.agent_token_id
                and pc.action == action
                and pc.payload == payload
                and pc.expires_at > now
            )
            if not valid:
                raise Forbidden("errors.confirmation_invalid")
            pc.status = "used"
            pc.used_at = now
        return
    with system_session() as sdb:
        pc = PendingConfirmation(
            tenant_id=actor.tenant_id,
            token_id=actor.agent_token_id,
            action=action,
            payload=payload,
            expires_at=now + timedelta(days=VALID_DAYS),
        )
        sdb.add(pc)
        sdb.flush()
        cid = str(pc.id)
    raise NeedsConfirmation(cid)
