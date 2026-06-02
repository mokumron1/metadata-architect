import pathlib
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from metadata_architect.config import get_settings

# Absolute path to the project root (two levels up from this file)
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    # SQLite doesn't support connection pool settings
    if url.startswith("sqlite"):
        # Replace relative ./path with absolute path so it works regardless of cwd
        if ":///./" in url:
            rel = url.split(":///./", 1)[1]
            url = f"sqlite+aiosqlite:///{_PROJECT_ROOT / rel}"
        return create_async_engine(url, echo=False, connect_args={"check_same_thread": False})
    return create_async_engine(
        url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        echo=False,
    )


engine = _make_engine()
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
