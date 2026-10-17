"""Background jobs of the time and cost model."""

from __future__ import annotations

from app.jobs.queue import JobContext, handler
from app.timemodel.service import refresh_all


@handler("estimates.refresh")
def refresh_estimates_job(ctx: JobContext) -> dict:
    n = refresh_all(
        ctx.db, ctx.tenant_id, progress=lambda f: ctx.progress(f, "Schätzungen werden aktualisiert …")
    )
    return {"orders": n}
