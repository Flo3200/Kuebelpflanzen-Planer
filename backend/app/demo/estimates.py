"""Demo step: compute estimates and prices for all demo orders."""

from __future__ import annotations

from app.demo.generator import step
from app.timemodel.service import refresh_all


@step
def estimates(db, tenant, rng, options, report, spec) -> None:
    report["estimates"] = refresh_all(db, tenant.id)
