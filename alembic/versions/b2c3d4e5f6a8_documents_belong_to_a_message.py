"""a document is attached to the message it was sent with

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f7
Create Date: 2026-09-20 00:00:00.000000

A file used to be attached to a conversation, which meant the conversation had
to exist first: you had to send a message before you could attach anything to
it. Now it is picked in the composer and sent with the message, so the thread
can show it on the bubble it came with. It still belongs to the conversation;
the message is what it arrived with.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("documents", sa.Column("message_id", sa.Integer(), nullable=True))
    op.create_index("ix_documents_message_id", "documents", ["message_id"])
    op.create_foreign_key(
        "fk_documents_message_id",
        "documents",
        "messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Files uploaded before this stay attached to their conversation only; there
    # is no message they can honestly be said to have arrived with.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_documents_message_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_message_id", table_name="documents")
    op.drop_column("documents", "message_id")
