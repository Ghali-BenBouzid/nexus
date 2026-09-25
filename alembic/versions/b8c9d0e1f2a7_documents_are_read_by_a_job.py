"""documents are read by a job

Revision ID: b8c9d0e1f2a7
Revises: e1f2a3b4c5d6
Create Date: 2026-09-25 00:00:01.000000

A file was read inside the request that uploaded it, and the message it came
with was only sent once that request returned. Reloading the page while a scan
was read killed both: the chat came back empty. The upload now only stores the
file and a job reads it, so the row says where the reading is and, when it
failed, why. Every existing document was read already.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

status = sa.Enum("reading", "ready", "failed", name="document_status")


def upgrade() -> None:
    status.create(op.get_bind())
    op.add_column(
        "documents",
        sa.Column("status", status, nullable=False, server_default="ready"),
    )
    op.add_column("documents", sa.Column("error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "error")
    op.drop_column("documents", "status")
    status.drop(op.get_bind())
