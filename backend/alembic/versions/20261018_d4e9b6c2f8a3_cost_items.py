"""own cost items per nursery, vehicle or staff member

Revision ID: d4e9b6c2f8a3
Revises: c3d8a5b1e7f2
Create Date: 2026-10-18 18:10:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.rls import apply_all

revision: str = "d4e9b6c2f8a3"
down_revision: str | None = "c3d8a5b1e7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cost_items",
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("amount_eur", sa.Float(), nullable=False),
        sa.Column("basis", sa.String(length=12), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(), nullable=True),
        sa.Column("staff_id", sa.Uuid(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["staff_id"], ["staff_members.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_cost_items_staff_id"), "cost_items", ["staff_id"], unique=False)
    op.create_index(op.f("ix_cost_items_tenant_id"), "cost_items", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_cost_items_vehicle_id"), "cost_items", ["vehicle_id"], unique=False)
    apply_all(op, {"cost_items": "strict"})


def downgrade() -> None:
    op.drop_index(op.f("ix_cost_items_vehicle_id"), table_name="cost_items")
    op.drop_index(op.f("ix_cost_items_tenant_id"), table_name="cost_items")
    op.drop_index(op.f("ix_cost_items_staff_id"), table_name="cost_items")
    op.drop_table("cost_items")
