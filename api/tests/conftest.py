from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config import Settings, get_settings
from app.db.models import Base
from app.db.seed.catalog import seed_catalog
from app.db.session import get_engine

API_ROOT = Path(__file__).parents[1]
SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def _normalise_url(database_url: str) -> str:
    return database_url.replace("postgresql+asyncpg", "postgresql").rstrip("/")


def _database_name(database_url: str) -> str:
    name = urlsplit(_normalise_url(database_url)).path.lstrip("/")
    if not SAFE_DATABASE_NAME.fullmatch(name):
        raise RuntimeError("Test database name must contain only letters, numbers, and underscores")
    return name


def _maintenance_url(database_url: str) -> str:
    parsed = urlsplit(_normalise_url(database_url))
    if not parsed.netloc:
        return f"{parsed.scheme}:///postgres"
    return urlunsplit((parsed.scheme, parsed.netloc, "/postgres", parsed.query, ""))


def _prepare_test_database(settings: Settings) -> None:
    if settings.app_env != "test":
        raise RuntimeError("Tests must run with APP_ENV=test")
    test_database_url = settings.resolved_database_url
    if _normalise_url(test_database_url) == _normalise_url(settings.database_url):
        raise RuntimeError("TEST_DATABASE_URL must differ from DATABASE_URL")

    database_name = _database_name(test_database_url)
    maintenance_url = _maintenance_url(test_database_url)
    exists = subprocess.run(
        [
            "psql",
            "-d",
            maintenance_url,
            "-tAc",
            "SELECT 1 FROM pg_database WHERE datname = %s" % repr(database_name),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    if exists.stdout.strip() != "1":
        subprocess.run(
            ["psql", "-d", maintenance_url, "-c", f'CREATE DATABASE "{database_name}"'],
            check=True,
        )

    environment = {**os.environ, "APP_ENV": "test"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
        cwd=API_ROOT,
        env=environment,
        check=True,
    )


async def _development_snapshot(settings: Settings) -> dict[str, tuple[int, object | None]]:
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            snapshot: dict[str, tuple[int, object | None]] = {}
            for table in Base.metadata.sorted_tables:
                count = await connection.scalar(select(func.count()).select_from(table))
                updated_at = table.c.get("updated_at")
                latest = (
                    await connection.scalar(select(func.max(updated_at)).select_from(table))
                    if updated_at is not None
                    else None
                )
                snapshot[table.name] = (count or 0, latest)
            return snapshot
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def test_database_guard() -> Iterator[None]:
    settings = get_settings()
    _prepare_test_database(settings)
    before = asyncio.run(_development_snapshot(settings))
    yield
    after = asyncio.run(_development_snapshot(settings))
    assert after == before, "Tests must not modify the development database"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = get_engine()
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_catalog(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await seed_catalog(db_session)
    yield db_session
