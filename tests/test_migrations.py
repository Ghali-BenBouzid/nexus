from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def test_migrations_form_a_single_chain() -> None:
    # The container runs `alembic upgrade head` at boot, which refuses to start when
    # two migrations share a parent. The suite runs on SQLite with create_all, so
    # nothing else would notice a forked history before deploy.
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))

    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1, f"migration history has several heads: {heads}"
