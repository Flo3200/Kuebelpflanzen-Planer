"""logistics focus: module switches (portal.enabled becomes modules.portal)

Revision ID: a1f0c3d9e201
Revises: d8e97b452695
Create Date: 2026-10-18 15:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f0c3d9e201"
down_revision: str | None = "d8e97b452695"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # the customer portal switch moves into the new modules group; values keep their level
    op.execute("UPDATE setting_values SET key = 'modules.portal' WHERE key = 'portal.enabled'")


def downgrade() -> None:
    op.execute("UPDATE setting_values SET key = 'portal.enabled' WHERE key = 'modules.portal'")
