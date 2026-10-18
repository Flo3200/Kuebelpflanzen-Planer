"""Background job for model fitting; periodic run per tenant (setting learning.schedule)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.jobs.queue import JobContext, handler
from app.jobs.worker import periodic
from app.learning.service import run_fit
from app.settings.service import SettingsResolver


@handler("learning.fit")
def fit_job(ctx: JobContext) -> dict:
    tenant_id = ctx.tenant_id or uuid.UUID(ctx.payload["tenant_id"])
    fit = run_fit(ctx.db, tenant_id, ctx.payload.get("tier"), progress=ctx.progress)
    return {
        "fit_id": str(fit.id),
        "n": fit.n_measurements,
        "mae_before": fit.metrics["before"].get("mae"),
        "mae_after": fit.metrics["after"].get("mae"),
    }


@periodic("learning.fit")
def due(db, tenant_id: uuid.UUID | None, now: datetime) -> str | None:
    if tenant_id is None:
        return None
    schedule = SettingsResolver(db, tenant_id).get("learning.schedule")
    if schedule == "weekly":
        y, w, _ = now.isocalendar()
        return f"{y}-W{w:02d}"
    if schedule == "monthly":
        return f"{now.year}-{now.month:02d}"
    return None
