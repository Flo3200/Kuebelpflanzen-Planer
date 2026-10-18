"""Demo step: synthetic measurements from known "true" values, so the model view has data.

The true values differ from the defaults on purpose; a model fit in the demo finds them again.
"""

from __future__ import annotations

from app.demo.generator import step
from app.learning.synthetic import generate

DEMO_TRUE_PARAMS = {"a0": 7.5, "a1": 0.1, "k_height": 0.7, "t_fixed": 12.0}


@step
def measurements(db, tenant, rng, options, report, spec) -> None:
    if not options.measurements:
        return
    out = generate(
        db,
        tenant.id,
        n=min(150, max(40, options.orders_per_tenant + 30)),
        true_params=DEMO_TRUE_PARAMS,
        noise_sigma=0.13,
        outlier_share=0.03,
        seed=rng.randint(1, 10_000),
    )
    report["measurements"] = out["created"]
