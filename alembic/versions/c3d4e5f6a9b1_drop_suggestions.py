"""a follow-up is prose, not a parsed field

Revision ID: c3d4e5f6a9b1
Revises: b2c3d4e5f6a8
Create Date: 2026-09-20 00:00:00.000000

The supervisor used to end every answer with a machine-readable <suggest> line
that code split into chips. A model that dropped the closing tag leaked the raw
markup into the reply, and the chips were a habit no answer needed. A follow-up
is now just a sentence the model writes when one is worth offering, so there is
nothing left to store.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a9b1"
down_revision: str | None = "b2c3d4e5f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("queries", "suggestions")


def downgrade() -> None:
    op.add_column(
        "queries",
        sa.Column(
            "suggestions",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=True,
        ),
    )
