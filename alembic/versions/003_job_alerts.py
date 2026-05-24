"""Job alerts table — saved natural-language queries that email matching new jobs.

Revision ID: 003
Revises: 002
Create Date: 2026-05-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), server_default="{}"),
        sa.Column("cadence", sa.Text(), server_default="daily"),
        sa.Column("is_confirmed", sa.Boolean(), server_default="false"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("confirm_token", sa.Text()),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
        sa.Column("last_match_count", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("idx_job_alerts_email", "job_alerts", ["email"])
    op.create_index(
        "idx_job_alerts_active_due",
        "job_alerts",
        ["is_active", "is_confirmed", "last_sent_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_job_alerts_active_due", table_name="job_alerts")
    op.drop_index("idx_job_alerts_email", table_name="job_alerts")
    op.drop_table("job_alerts")
