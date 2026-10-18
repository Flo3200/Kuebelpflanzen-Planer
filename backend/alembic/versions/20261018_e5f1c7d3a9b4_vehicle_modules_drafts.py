"""modular vehicles: modules, module links, vehicle drafts from photo or chat; module cost items;
test sets for further AI functions

Revision ID: e5f1c7d3a9b4
Revises: d4e9b6c2f8a3
Create Date: 2026-10-18 19:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import apply_all

revision: str = "e5f1c7d3a9b4"
down_revision: str | None = "d4e9b6c2f8a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _base() -> list:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    ]


def upgrade() -> None:
    op.create_table(
        "vehicle_modules",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("x_cm", sa.Float(), nullable=False),
        sa.Column("y_cm", sa.Float(), nullable=False),
        sa.Column("length_cm", sa.Float(), nullable=False),
        sa.Column("depth_cm", sa.Float(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("clearance_cm", sa.Float(), nullable=True),
        sa.Column("max_load_kg", sa.Float(), nullable=True),
        sa.Column("blocks_floor", sa.Boolean(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        *_base(),
    )
    op.create_index(op.f("ix_vehicle_modules_tenant_id"), "vehicle_modules", ["tenant_id"], unique=False)
    op.create_table(
        "vehicle_module_links",
        sa.Column("vehicle_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["module_id"], ["vehicle_modules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("vehicle_id", "module_id"),
        *_base(),
    )
    op.create_index(op.f("ix_vehicle_module_links_module_id"), "vehicle_module_links", ["module_id"], unique=False)
    op.create_index(op.f("ix_vehicle_module_links_tenant_id"), "vehicle_module_links", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_vehicle_module_links_vehicle_id"), "vehicle_module_links", ["vehicle_id"], unique=False)
    op.create_table(
        "vehicle_drafts",
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("review_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("photo_file_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_vehicle_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
        *_base(),
    )
    op.create_index(op.f("ix_vehicle_drafts_tenant_id"), "vehicle_drafts", ["tenant_id"], unique=False)
    op.add_column("cost_items", sa.Column("module_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "cost_items_module_id_fkey", "cost_items", "vehicle_modules", ["module_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(op.f("ix_cost_items_module_id"), "cost_items", ["module_id"], unique=False)
    # the evaluation tool gets test sets for other AI functions (vehicle photo and chat)
    op.add_column("eval_sets", sa.Column("function", sa.String(length=40), server_default="photo_analysis", nullable=False))
    op.add_column("eval_items", sa.Column("input_text", sa.Text(), nullable=True))
    apply_all(op, {"vehicle_modules": "strict", "vehicle_module_links": "strict", "vehicle_drafts": "strict"})


def downgrade() -> None:
    op.drop_column("eval_items", "input_text")
    op.drop_column("eval_sets", "function")
    op.drop_index(op.f("ix_cost_items_module_id"), table_name="cost_items")
    op.drop_constraint("cost_items_module_id_fkey", "cost_items", type_="foreignkey")
    op.drop_column("cost_items", "module_id")
    op.drop_index(op.f("ix_vehicle_drafts_tenant_id"), table_name="vehicle_drafts")
    op.drop_table("vehicle_drafts")
    op.drop_index(op.f("ix_vehicle_module_links_vehicle_id"), table_name="vehicle_module_links")
    op.drop_index(op.f("ix_vehicle_module_links_tenant_id"), table_name="vehicle_module_links")
    op.drop_index(op.f("ix_vehicle_module_links_module_id"), table_name="vehicle_module_links")
    op.drop_table("vehicle_module_links")
    op.drop_index(op.f("ix_vehicle_modules_tenant_id"), table_name="vehicle_modules")
    op.drop_table("vehicle_modules")
