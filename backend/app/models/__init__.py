"""Import every model module so that Base.metadata is complete."""

from app.models import ai, core, masterdata, orders  # noqa: F401
from app.models.base import Base, rls_tables  # noqa: F401
