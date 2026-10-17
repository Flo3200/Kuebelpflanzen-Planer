"""Inheritance chains for object-level settings.

A chain lists the objects whose values are consulted before tenant and platform values,
most specific first. Object kinds register a builder (e.g. plant -> species).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.settings.service import ChainItem

CHAIN_BUILDERS: dict[str, Callable[[Session, uuid.UUID], list[ChainItem]]] = {}


def chain_for(db: Session, scope: str, object_id: uuid.UUID) -> list[ChainItem]:
    builder = CHAIN_BUILDERS.get(scope)
    if builder is None:
        return [(scope, object_id)]
    return builder(db, object_id)
