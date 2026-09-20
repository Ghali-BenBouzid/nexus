"""a query becomes a run with a kind, and plan approval goes away

Revision ID: a1b2c3d4e5f7
Revises: f0a1b2c3d4e5
Create Date: 2026-09-20 00:00:00.000000

A chat turn, a deep research run and a fact check are the same row with a
different ``kind``: each needs an owner, a status, a heartbeat, an event feed, a
stop and a bill. ``conversation_id`` is what lets a background run find its way
back to the thread that started it, since it finishes long after that turn has.

Plan approval is removed entirely: the supervisor decides what work a message
needs and does it, so there is no plan to confirm. Any run still paused on one
is failed, because nothing is left that could resume it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f7"
down_revision: str | Sequence[str] | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "queries",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="chat"),
    )
    op.create_index("ix_queries_kind", "queries", ["kind"])
    op.add_column("queries", sa.Column("conversation_id", sa.Integer(), nullable=True))
    op.create_index("ix_queries_conversation_id", "queries", ["conversation_id"])
    op.create_foreign_key(
        "fk_queries_conversation_id",
        "queries",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.add_column("queries", sa.Column("suggestions", _JSON, nullable=True))

    # Backfill: every existing turn belongs to the conversation whose message
    # points at it. A one-shot API run has no message and stays null.
    op.execute(
        """
        UPDATE queries SET conversation_id = m.conversation_id
        FROM messages m WHERE m.query_id = queries.id
        """
    )
    # Nothing can resume a plan that is waiting for a confirmation the app no
    # longer asks for.
    op.execute(
        "UPDATE queries SET status = 'failed', "
        "error = 'Plan approval was removed; send the question again.' "
        "WHERE status = 'awaiting_plan'"
    )
    op.drop_column("queries", "plan")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("queries", sa.Column("plan", _JSON, nullable=True))
    op.drop_column("queries", "suggestions")
    op.drop_constraint("fk_queries_conversation_id", "queries", type_="foreignkey")
    op.drop_index("ix_queries_conversation_id", table_name="queries")
    op.drop_column("queries", "conversation_id")
    op.drop_index("ix_queries_kind", table_name="queries")
    op.drop_column("queries", "kind")
    # Postgres has no clean DROP VALUE for an enum; the unused 'awaiting_plan'
    # value is harmless, and the downgrade leaves it in place.
