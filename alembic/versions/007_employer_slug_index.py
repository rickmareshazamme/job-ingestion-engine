"""Step 4/4 of employer slug: index slug column for fast lookups.

Non-unique on purpose — uniqueness is enforced by the trigger in 005.
A unique constraint could break inserts if the trigger fails to find
a unique candidate (cosmic edge case, but better safe).

Revision ID: 007
Revises: 006
Create Date: 2026-05-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_employers_slug ON employers (slug)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_employers_slug")
