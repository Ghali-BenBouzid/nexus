"""a conversation is named by an opaque id outside the database

Revision ID: d4e5f6a7b8c2
Revises: c3d4e5f6a9b1
Create Date: 2026-09-22 00:00:00.000000

Conversation ids count up across every account, and they were the URL: a link
to /chat/26 said how many chats everyone had had, and the next one was one
guess away. Each conversation now gets a random UUID that the URL and the API
use instead; the integer id stays the key everything joins on.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c2"
down_revision: str | None = "c3d4e5f6a9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The database fills it in, for the chats that already exist and for any
    # insert that does not set one: code still running from before this
    # migration (a rolling deploy) knows nothing about the column.
    op.add_column(
        "conversations",
        sa.Column(
            "public_id",
            sa.Uuid(),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.create_index(
        "ix_conversations_public_id", "conversations", ["public_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_public_id", table_name="conversations")
    op.drop_column("conversations", "public_id")
