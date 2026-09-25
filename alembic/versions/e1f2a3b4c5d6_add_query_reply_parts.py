"""reply parts on queries

A chat reply is written in parts: what the supervisor says before each round of
tool calls, then its answer. The parts are kept as well as the joined reply, so
a reloaded thread can put the work back between them.

Revision ID: e1f2a3b4c5d6
Revises: f6a7b8c9d0e4
Create Date: 2026-09-25 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "f6a7b8c9d0e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "queries",
        sa.Column(
            "reply_parts",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("queries", "reply_parts")
