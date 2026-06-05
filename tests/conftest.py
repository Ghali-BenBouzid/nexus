from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from main import app


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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # creating tables

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)  # cleaning up
    await engine.dispose()
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    await client.post(
        "/auth/register", json={"email": "test@test.com", "password": "secret"}
    )

    response = await client.post(
        "/auth/login", data={"username": "test@test.com", "password": "secret"}
    )

    token = response.json()["access_token"]

    return {"Authorization": f"Bearer {token}"}
