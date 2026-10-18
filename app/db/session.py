import asyncio
import contextlib
from collections.abc import AsyncGenerator, Awaitable

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    url=settings.database_url,
    connect_args=settings.db_connect_args,
    **settings.db_engine_args,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


async def finish_then_cancel[T](write: Awaitable[T]) -> T:
    """Run a short write to its end even if the caller is cancelled meanwhile,
    then let the cancellation through. A stopped run is cancelled wherever it is;
    cut mid-statement, the driver throws its connection away (a fresh login
    behind the pooler, a held lock on SQLite) and the row is lost, which for a
    billing line means a call nobody paid for."""
    task = asyncio.ensure_future(write)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with contextlib.suppress(Exception):
            await task
        raise


async def get_db() -> AsyncGenerator[AsyncSession]:
    async with SessionLocal() as db:
        yield db
