"""species in the background: species name and properties on the plant

Revision ID: b7c41e2f9a10
Revises: a1f0c3d9e201
Create Date: 2026-10-18 16:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c41e2f9a10"
down_revision: str | None = "a1f0c3d9e201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW = ("species_name", "species_source", "soil_kg_per_l", "plant_kg_per_l", "trunk_kg_per_m", "tip_tendency")


def upgrade() -> None:
    op.add_column("plants", sa.Column("species_name", sa.String(length=160), nullable=True))
    op.add_column("plants", sa.Column("species_source", sa.String(length=20), nullable=True))
    op.add_column("plants", sa.Column("soil_kg_per_l", sa.Float(), nullable=True))
    op.add_column("plants", sa.Column("plant_kg_per_l", sa.Float(), nullable=True))
    op.add_column("plants", sa.Column("trunk_kg_per_m", sa.Float(), nullable=True))
    op.add_column("plants", sa.Column("tip_tendency", sa.Float(), nullable=True))
    # copy the values of the species to every plant (only the new columns, so downgrade is exact)
    op.execute(
        """
        UPDATE plants p SET
            species_name = s.name,
            species_source = 'migrated',
            soil_kg_per_l = s.soil_kg_per_l,
            plant_kg_per_l = s.plant_kg_per_l,
            trunk_kg_per_m = s.trunk_kg_per_m,
            tip_tendency = s.tip_tendency
        FROM species s
        WHERE s.id = p.species_id
        """
    )


def downgrade() -> None:
    for col in reversed(NEW):
        op.drop_column("plants", col)
