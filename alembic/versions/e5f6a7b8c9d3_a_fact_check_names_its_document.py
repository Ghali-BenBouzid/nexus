"""a fact check names the document it checks

Revision ID: e5f6a7b8c9d3
Revises: d4e5f6a7b8c2
Create Date: 2026-09-25 00:00:00.000000

The document a fact check read travelled only in its job's arguments, so
nothing could tell that a document was already being checked, and a "tell me
jokes while I wait" started a second check of the same CV. The run's row now
says which document it is checking. Nullable: every other kind of run has none,
and a check outlives the file it read when the file is removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5f6a7b8c9d3"
down_revision: str | None = "d4e5f6a7b8c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("queries", sa.Column("document_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_queries_document_id",
        "queries",
        "documents",
        ["document_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_queries_document_id", "queries", type_="foreignkey")
    op.drop_column("queries", "document_id")
