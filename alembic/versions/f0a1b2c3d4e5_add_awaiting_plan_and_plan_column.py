"""add awaiting_plan status and plan column for human-in-the-loop confirmation

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # New status for a plan paused for the user to confirm or revise.
    op.execute("ALTER TYPE query_status ADD VALUE IF NOT EXISTS 'awaiting_plan'")
    op.add_column(
        "queries",
        sa.Column(
            "plan",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("queries", "plan")
    # Postgres has no clean DROP VALUE for an enum; the unused value is harmless.
