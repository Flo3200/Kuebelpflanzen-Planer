"""Imports the demo-data steps of all phases (each module registers itself with @step)."""

import importlib

for _mod in (
    "app.demo.masterdata",
    "app.demo.orders",
    "app.demo.estimates",
    "app.demo.measurements",
):
    try:
        importlib.import_module(_mod)
    except ModuleNotFoundError as exc:  # module of a later phase not present yet
        if exc.name != _mod:
            raise
