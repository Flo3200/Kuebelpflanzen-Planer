"""round 2: notifications, customer share links, formula debates, spontaneous teams

Revision ID: a7c3e9f1d2b6
Revises: f6a2d8e4b0c5
Create Date: 2026-10-22 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import apply_all

revision: str = "a7c3e9f1d2b6"
down_revision: str | None = "f6a2d8e4b0c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("link", sa.String(length=300), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        *_base_columns(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"])
    op.create_index(op.f("ix_notifications_draft_id"), "notifications", ["draft_id"])
    op.create_index(op.f("ix_notifications_order_id"), "notifications", ["order_id"])

    op.create_table(
        "share_links",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploads", sa.Integer(), nullable=False),
        sa.Column("location", JSONB, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        *_base_columns(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_share_links_tenant_id"), "share_links", ["tenant_id"])
    op.create_index(op.f("ix_share_links_draft_id"), "share_links", ["draft_id"])
    op.create_index(op.f("ix_share_links_order_id"), "share_links", ["order_id"])

    op.create_table(
        "formula_debates",
        sa.Column("formula_key", sa.String(length=30), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("model_a_id", sa.Uuid(), nullable=True),
        sa.Column("model_b_id", sa.Uuid(), nullable=True),
        sa.Column("n_rounds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("rounds", JSONB, nullable=False),
        sa.Column("proposal", JSONB, nullable=False),
        sa.Column("evaluation", JSONB, nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("adopted_version_id", sa.Uuid(), nullable=True),
        *_base_columns(),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_formula_debates_tenant_id"), "formula_debates", ["tenant_id"])

    op.add_column("teams", sa.Column("ad_hoc", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("teams", sa.Column("source_text", sa.Text(), nullable=True))

    apply_all(op, {"notifications": "strict", "share_links": "strict", "formula_debates": "shared"})


def downgrade() -> None:
    op.drop_column("teams", "source_text")
    op.drop_column("teams", "ad_hoc")
    op.drop_index(op.f("ix_formula_debates_tenant_id"), table_name="formula_debates")
    op.drop_table("formula_debates")
    for ix in ("order_id", "draft_id", "tenant_id"):
        op.drop_index(op.f(f"ix_share_links_{ix}"), table_name="share_links")
    op.drop_table("share_links")
    for ix in ("order_id", "draft_id", "tenant_id"):
        op.drop_index(op.f(f"ix_notifications_{ix}"), table_name="notifications")
    op.drop_table("notifications")
