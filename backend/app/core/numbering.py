"""Gap-free sequential numbers per tenant (row lock on the counter)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.orders import Counter


def next_number(db: Session, tenant_id: uuid.UUID | None, name: str) -> int:
    if tenant_id is None:
        raise ValueError("platform counters use app.billing.numbering")
    db.execute(
        insert(Counter)
        .values(tenant_id=tenant_id, name=name, value=0)
        .on_conflict_do_nothing(index_elements=["tenant_id", "name"])
    )
    counter = db.scalar(
        select(Counter).where(Counter.tenant_id == tenant_id, Counter.name == name).with_for_update()
    )
    assert counter is not None
    counter.value += 1
    db.flush()
    return counter.value
