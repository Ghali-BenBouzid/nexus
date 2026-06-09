"""add status, error, result, completed_at to queries

Revision ID: c3a1b2d4e5f6
Revises: a62f9ceac132
Create Date: 2026-06-09 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a1b2d4e5f6"
down_revision: str | Sequence[str] | None = "a62f9ceac132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    query_status = postgresql.ENUM(
        "pending",
        "running",
        "complete",
        "failed",
        name="query_status",
    )
    query_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "queries",
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending",
                "running",
                "complete",
                "failed",
                name="query_status",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
    )
    op.add_column("queries", sa.Column("error", sa.Text(), nullable=True))
    op.add_column(
        "queries",
        sa.Column(
            "result",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
    op.add_column(
        "queries",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("queries", "completed_at")
    op.drop_column("queries", "result")
    op.drop_column("queries", "error")
    op.drop_column("queries", "status")
    sa.Enum(name="query_status").drop(op.get_bind(), checkfirst=True)
