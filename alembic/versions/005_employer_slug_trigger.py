"""Step 2/4 of employer slug: BEFORE INSERT/UPDATE trigger auto-fills slug
from employer name, resolving collisions by appending -2, -3, ...

Idempotent: CREATE OR REPLACE FUNCTION + DROP/CREATE TRIGGER.

Revision ID: 005
Revises: 004
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
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
    op.execute(TRIGGER_FN)
    op.execute("DROP TRIGGER IF EXISTS employers_set_slug_trigger ON employers")
    op.execute("""
        CREATE TRIGGER employers_set_slug_trigger
          BEFORE INSERT OR UPDATE OF name, slug ON employers
          FOR EACH ROW
          EXECUTE FUNCTION employers_set_slug();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS employers_set_slug_trigger ON employers")
    op.execute("DROP FUNCTION IF EXISTS employers_set_slug()")
