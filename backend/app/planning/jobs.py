"""Background jobs of the tour planning."""

from __future__ import annotations

import traceback
import uuid

from app.core.db import system_session
from app.jobs.queue import JobContext, handler
from app.models.planning import Plan
from app.planning.planner import run_plan


@handler("planning.solve")
def solve_job(ctx: JobContext) -> dict:
    plan = ctx.db.get(Plan, uuid.UUID(ctx.payload["plan_id"]))
    plan.status = "computing"
    ctx.db.commit()
    try:
        run_plan(ctx.db, plan, progress=lambda f, m: ctx.progress(f, m))
    except Exception as exc:
        ctx.db.rollback()
        with system_session() as db:
            p = db.get(Plan, plan.id)
            p.status = "failed"
            p.error = f"{type(exc).__name__}: {exc}"[:2000] + "\n" + traceback.format_exc(limit=5)
        raise
    return {"plan_id": str(plan.id), "kpis": {k: v for k, v in plan.kpis.items() if k != "per_day"}}
