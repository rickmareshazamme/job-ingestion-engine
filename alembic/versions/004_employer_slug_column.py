"""Step 1/4 of employer slug: add nullable slug column.

Kept in its own revision so a failure of the trigger/backfill/index
steps doesn't roll the column add back.

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


def upgrade() -> None:
    op.execute("ALTER TABLE employers ADD COLUMN IF NOT EXISTS slug TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE employers DROP COLUMN IF EXISTS slug")
