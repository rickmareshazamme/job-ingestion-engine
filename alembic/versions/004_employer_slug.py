"""Employer slug column — human-readable URL identifier derived from name.

Adds employers.slug (unique), a BEFORE INSERT/UPDATE trigger that auto-fills
it from name with collision suffixes, and backfills every existing row.

Revision ID: 004
Revises: 003
Create Date: 2026-05-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TRIGGER_FN = """
CREATE OR REPLACE FUNCTION employers_set_slug() RETURNS trigger AS $$
DECLARE
  base text;
  candidate text;
  i int := 1;
BEGIN
  IF NEW.slug IS NULL OR NEW.slug = '' THEN
    base := nullif(trim(BOTH '-' FROM regexp_replace(lower(coalesce(NEW.name, '')), '[^a-z0-9]+', '-', 'g')), '');
    base := coalesce(base, 'employer');
    candidate := base;
    WHILE EXISTS (SELECT 1 FROM employers WHERE slug = candidate AND id <> NEW.id) LOOP
      i := i + 1;
      candidate := base || '-' || i;
    END LOOP;
    NEW.slug := candidate;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column("employers", sa.Column("slug", sa.Text(), nullable=True))

    op.execute(TRIGGER_FN)
    op.execute("""
        CREATE TRIGGER employers_set_slug_trigger
          BEFORE INSERT OR UPDATE OF name, slug ON employers
          FOR EACH ROW
          EXECUTE FUNCTION employers_set_slug();
    """)

    # Backfill all existing rows. ROW_NUMBER over partition handles collisions
    # by appending -2, -3, ... to the second+ rows that share a base slug.
    op.execute("""
        WITH bases AS (
          SELECT
            id,
            coalesce(
              nullif(trim(BOTH '-' FROM regexp_replace(lower(coalesce(name, '')), '[^a-z0-9]+', '-', 'g')), ''),
              'employer'
            ) AS base,
            created_at
          FROM employers
        ),
        ranked AS (
          SELECT
            id,
            base,
            ROW_NUMBER() OVER (PARTITION BY base ORDER BY created_at NULLS LAST, id) AS rn
          FROM bases
        )
        UPDATE employers e
        SET slug = CASE WHEN r.rn = 1 THEN r.base ELSE r.base || '-' || r.rn END
        FROM ranked r
        WHERE e.id = r.id;
    """)

    op.create_index("ix_employers_slug", "employers", ["slug"], unique=True)
    op.alter_column("employers", "slug", nullable=False)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS employers_set_slug_trigger ON employers")
    op.execute("DROP FUNCTION IF EXISTS employers_set_slug()")
    op.drop_index("ix_employers_slug", table_name="employers")
    op.drop_column("employers", "slug")
