"""Daily retention run per tenant."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.jobs.queue import JobContext, handler
from app.jobs.worker import periodic
from app.privacy.service import run_retention


@handler("privacy.retention")
def retention_job(ctx: JobContext) -> dict:
    tenant_id = ctx.tenant_id or uuid.UUID(ctx.payload["tenant_id"])
    return run_retention(ctx.db, ctx.actor, tenant_id)


@periodic("privacy.retention")
def due(db, tenant_id: uuid.UUID | None, now: datetime) -> str | None:
    return None if tenant_id is None else now.strftime("%Y-%m-%d")
