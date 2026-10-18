"""Import every model module so that Base.metadata is complete."""

from app.models import (  # noqa: F401
    ai,
    core,
    costs,
    field,
    fleet,
    formulas,
    masterdata,
    orders,
    packing,
    planning,
    platform,
)
from app.models.base import Base, rls_tables  # noqa: F401
from app.routing import provider as _routing  # noqa: F401,E402  (route_cache table)
