"""Human confirmation for destructive or billing-relevant agent actions.

Phase 1 placeholder: agents may not perform such actions at all. Phase 7 replaces this with
a pending-confirmation queue shown in the UI.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.context import Actor
from app.core.errors import Forbidden


def confirm_if_agent(db: Session, actor: Actor, action: str, payload: dict[str, Any]) -> None:
    if actor.via == "agent":
        raise Forbidden("errors.needs_confirmation")
