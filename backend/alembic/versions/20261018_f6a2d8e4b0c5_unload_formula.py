"""unloading from a formula: depot window per tour, unloading measurements

Revision ID: f6a2d8e4b0c5
Revises: e5f1c7d3a9b4
Create Date: 2026-10-18 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import apply_all

revision: str = "f6a2d8e4b0c5"
down_revision: str | None = "e5f1c7d3a9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tours", sa.Column("depot_start_min", sa.Integer(), nullable=True))
    op.add_column("tours", sa.Column("depot_end_min", sa.Integer(), nullable=True))
    op.add_column("tours", sa.Column("unload_min", sa.Float(), nullable=True))
    op.create_table(
        "unload_measurements",
        sa.Column("tour_id", sa.Uuid(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=12), nullable=False),
        sa.Column("team_size", sa.Integer(), nullable=False),
        sa.Column("n_plants", sa.Integer(), nullable=False),
        sa.Column("total_weight", sa.Float(), nullable=False),
        sa.Column("n_stops", sa.Integer(), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("minutes", sa.Float(), nullable=False),
        sa.Column("predicted_min", sa.Float(), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tour_id"], ["tours.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_unload_measurements_tenant_id"), "unload_measurements", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_unload_measurements_tour_id"), "unload_measurements", ["tour_id"], unique=True)
    apply_all(op, {"unload_measurements": "strict"})


def downgrade() -> None:
    op.drop_index(op.f("ix_unload_measurements_tour_id"), table_name="unload_measurements")
    op.drop_index(op.f("ix_unload_measurements_tenant_id"), table_name="unload_measurements")
    op.drop_table("unload_measurements")
    op.drop_column("tours", "unload_min")
    op.drop_column("tours", "depot_end_min")
    op.drop_column("tours", "depot_start_min")
