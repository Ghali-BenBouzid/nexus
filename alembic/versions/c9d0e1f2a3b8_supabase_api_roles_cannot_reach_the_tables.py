"""supabase api roles cannot reach the tables

Revision ID: c9d0e1f2a3b8
Revises: b8c9d0e1f2a7
Create Date: 2026-10-18 00:00:00.000000

Supabase grants its Data API roles, anon and authenticated, every privilege on
whatever is created in the public schema, and Nexus's tables have no row level
security: anyone holding the project's anon key could read or rewrite users and
messages over HTTP. Nexus never uses that API; it connects as the owner, which
these grants do not touch. Revoke them on what exists, and in the default
privileges so the tables later migrations (and the checkpointer) create are
never granted either. A database without those roles (local, Neon) is left as
it is.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d0e1f2a3b8"
down_revision: str | None = "b8c9d0e1f2a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF (SELECT count(*) FROM pg_roles
              WHERE rolname IN ('anon', 'authenticated')) = 2 THEN
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
            REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              REVOKE ALL ON TABLES FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              REVOKE ALL ON SEQUENCES FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public
              REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
          END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Handing the data back to anyone with the anon key is never wanted.
    pass
