"""Employer LinkedIn fields — company_id + poster_email for XML job feed

Revision ID: 002
Revises: 001
Create Date: 2026-05-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("employers", sa.Column("linkedin_company_id", sa.Text(), nullable=True))
    op.add_column("employers", sa.Column("linkedin_poster_email", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("employers", "linkedin_poster_email")
    op.drop_column("employers", "linkedin_company_id")
