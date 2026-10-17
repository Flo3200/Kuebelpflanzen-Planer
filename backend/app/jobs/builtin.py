"""Small built-in job handlers."""

from __future__ import annotations

import time

from app.jobs.queue import JobContext, handler


@handler("system.echo")
def echo(ctx: JobContext) -> dict:
    """Test job: reports progress in steps and returns its payload."""
    steps = int(ctx.payload.get("steps", 3))
    for i in range(steps):
        ctx.progress((i + 1) / steps, f"Schritt {i + 1} von {steps}")
        time.sleep(float(ctx.payload.get("sleep", 0)))
    return {"echo": ctx.payload}
