"""messages carry the questions of a question panel, turns their mode

Revision ID: f6a7b8c9d0e4
Revises: e5f6a7b8c9d3
Create Date: 2026-09-25 00:00:00.000000

The supervisor can end a turn by asking the user questions with options. The
questions ride on the assistant message that asked them, and the answers on the
user message that came back, so the panel and the answered card both come from
the thread. Nullable: almost no message has one.

A turn also records the composer mode it was sent in. A brainstorm before a
deep run is a string of questions asked in deep mode; reopened after a reload,
the conversation came back in the ordinary mode, and the answer to the next
question was read as a plain question. The mode of the turn that asked is what
the composer is put back in.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a7b8c9d0e4"
down_revision: str | None = "e5f6a7b8c9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("ask", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("queries", sa.Column("mode", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("queries", "mode")
    op.drop_column("messages", "ask")
