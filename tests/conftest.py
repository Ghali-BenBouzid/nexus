from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db import session as db_session
from app.db.base import Base
from app.db.session import get_db
from main import app
from tests.accounts import login_as


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    # In-memory async SQLite. StaticPool keeps a single shared connection so the
    # schema created below is visible to every request in the test.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # creating tables

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # cleaning up
    await engine.dispose()
    db_session.SessionLocal = original_session_local
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    return await login_as(client)
