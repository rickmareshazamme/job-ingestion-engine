"""Step 3/4 of employer slug: backfill existing rows.

Only updates rows where slug IS NULL, so a re-run is a no-op. Uses
ROW_NUMBER over base-slug partitions to disambiguate collisions
deterministically.

Revision ID: 006
Revises: 005
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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
          WHERE slug IS NULL
        ),
        existing AS (
          SELECT slug FROM employers WHERE slug IS NOT NULL
        ),
        ranked AS (
          SELECT
            id,
            base,
            ROW_NUMBER() OVER (PARTITION BY base ORDER BY created_at NULLS LAST, id) AS rn
          FROM bases
        ),
        candidates AS (
          SELECT
            id,
            CASE WHEN rn = 1 THEN base ELSE base || '-' || rn END AS candidate
          FROM ranked
        )
        UPDATE employers e
        SET slug = c.candidate
        FROM candidates c
        WHERE e.id = c.id
          AND e.slug IS NULL
          AND NOT EXISTS (SELECT 1 FROM existing ex WHERE ex.slug = c.candidate);
    """)
    op.execute("""
        UPDATE employers
        SET slug = nullif(trim(BOTH '-' FROM regexp_replace(lower(coalesce(name, '')), '[^a-z0-9]+', '-', 'g')), '') || '-' || left(replace(id::text, '-', ''), 8)
        WHERE slug IS NULL;
    """)


def downgrade() -> None:
    pass
