"""teams by the owner: weekdays and validity period of fixed teams

Revision ID: c3d8a5b1e7f2
Revises: b7c41e2f9a10
Create Date: 2026-10-18 17:20:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3d8a5b1e7f2"
down_revision: str | None = "b7c41e2f9a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column("weekdays", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
    )
    op.add_column("teams", sa.Column("valid_from", sa.Date(), nullable=True))
    op.add_column("teams", sa.Column("valid_to", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("teams", "valid_to")
    op.drop_column("teams", "valid_from")
    op.drop_column("teams", "weekdays")
