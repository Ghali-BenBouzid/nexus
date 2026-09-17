from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db import session as db_session
from app.db.base import Base
from app.db.session import get_db
from app.research import service as research_service
from main import app
from tests.accounts import login_as


@pytest_asyncio.fixture
async def client(tmp_path) -> AsyncGenerator[AsyncClient]:
    # A throwaway SQLite file, and a connection per session: a job's heartbeat,
    # its event writes and the test's own writes run as separate transactions,
    # as they do on Postgres. One shared in-memory connection let a session
    # closing roll back another's uncommitted write, which made tests flaky.
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        connect_args={"timeout": 30},  # concurrent writers wait instead of failing
        poolclass=NullPool,
    )

    session_local = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    async def get_test_db() -> AsyncGenerator[AsyncSession]:
        async with session_local() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    # Background jobs, the event feed and the usage ledger open their OWN sessions
    # via db_session.SessionLocal (not a Depends), so point it at the test engine.
    original_session_local = db_session.SessionLocal
    db_session.SessionLocal = session_local
    # No Redis in the tests: jobs run in-process after each response, with the
    # request's (fake) provider and backend.
    original_queue = settings.job_queue
    settings.job_queue = "inline"
    await research_service.open_graph(in_memory=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # creating tables

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # cleaning up
    await engine.dispose()
    db_session.SessionLocal = original_session_local
    settings.job_queue = original_queue
    await research_service.close_graph()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    return await login_as(client)


# The external API keys a developer's .env may hold. CI has none of them.
_API_KEYS = (
    "openrouter_api_key",
    "gemini_api_key",
    "groq_api_key",
    "cerebras_api_key",
    "sambanova_api_key",
    "tavily_api_key",
    "langsmith_api_key",
)


@pytest.fixture(autouse=True)
def no_real_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as CI does, with no real provider or search keys, so a test
    that forgets its fakes fails on a laptop too instead of only in CI."""
    for name in _API_KEYS:
        monkeypatch.setattr(settings, name, None)
