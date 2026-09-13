"""invite-only demo accounts with a dollar budget, and the llm_usage ledger

Replaces open email/password signup with admin-created accounts reached through an
invite link: users lose hashed_password and gain a display name, the invite token
hash, a budget and an expiry. llm_usage records the cost of every model call.

Existing rows (the old auto-created browser accounts) are kept with their email as
their name, but they have no invite token, so nobody can sign into them anymore.

Revision ID: a8b9c0d1e2f3
Revises: f0a1b2c3d4e5
Create Date: 2026-09-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("name", sa.Text(), nullable=True))
    op.execute("UPDATE users SET name = email")
    op.alter_column("users", "name", nullable=False)
    op.alter_column("users", "email", existing_type=sa.String(), nullable=True)
    op.drop_column("users", "hashed_password")
    op.add_column(
        "users", sa.Column("invite_token_hash", sa.String(length=64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_users_invite_token_hash", "users", ["invite_token_hash"]
    )
    # The server default only backfills existing rows; new accounts always get an
    # explicit budget from the app, so the default is dropped right after.
    op.add_column(
        "users",
        sa.Column(
            "budget_micro_usd",
            sa.BigInteger(),
            nullable=False,
            server_default="500000",
        ),
    )
    op.alter_column("users", "budget_micro_usd", server_default=None)
    op.add_column(
        "users", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "llm_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "query_id",
            sa.Integer(),
            sa.ForeignKey("queries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_micro_usd", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_llm_usage_user_id", table_name="llm_usage")
    op.drop_table("llm_usage")
    op.drop_column("users", "created_at")
    op.drop_column("users", "expires_at")
    op.drop_column("users", "budget_micro_usd")
    op.drop_constraint("uq_users_invite_token_hash", "users", type_="unique")
    op.drop_column("users", "invite_token_hash")
    # Password hashes are gone for good; the column comes back empty and nullable.
    op.add_column("users", sa.Column("hashed_password", sa.String(), nullable=True))
    # Fails if an invite-only account has no email; fill them in first.
    op.alter_column("users", "email", existing_type=sa.String(), nullable=False)
    op.drop_column("users", "name")
