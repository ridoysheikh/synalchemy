"""Engine construction: async and sync engines, pool selection, database creation.

Pool kinds (``pool = "..."`` per database or in ``engine_defaults``):

========== ============================== =============================================
kind       pool class                     use it for
========== ============================== =============================================
``auto``   dialect default                most apps (default)
``queue``  QueuePool / AsyncAdaptedQueue  long-running servers; tune ``pool_size`` etc.
``null``   NullPool                       CLIs, serverless, external poolers (PgBouncer)
``static`` StaticPool                     one shared connection (in-memory SQLite, tests)
``single`` SingletonThreadPool (sync)     one connection per thread
========== ============================== =============================================

Queue-only options (``pool_size``, ``max_overflow``, ...) are dropped automatically for
pools that don't accept them, so switching ``pool`` never breaks the config.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import (
    AsyncAdaptedQueuePool,
    NullPool,
    QueuePool,
    SingletonThreadPool,
    StaticPool,
)

from synalchemy.exceptions import ConfigError

if TYPE_CHECKING:
    from synalchemy.config import DatabaseConfig

POOL_KINDS = ("auto", "queue", "null", "static", "single")

# Options only QueuePool-style pools accept.
_QUEUE_ONLY = {"pool_size", "max_overflow", "pool_timeout", "pool_use_lifo"}

# Async driver -> sync driver for the same backend. Drivers not listed serve both.
_SYNC_DRIVERS = {
    "aiosqlite": "pysqlite",
    "aiomysql": "pymysql",
    "asyncmy": "pymysql",
    "aioodbc": "pyodbc",
    "psycopg_async": "psycopg",
}


def is_memory_sqlite(url: str) -> bool:
    parsed = make_url(url)
    return parsed.get_backend_name() == "sqlite" and parsed.database in (None, "", ":memory:")


def to_sync_url(url: str) -> str:
    """Swap an async driver for its sync counterpart."""
    parsed = make_url(url)
    backend, _, driver = parsed.drivername.partition("+")
    if driver == "asyncpg":
        driver = next((d for d in ("psycopg", "psycopg2") if importlib.util.find_spec(d)), "")
        if not driver:
            raise ConfigError(
                "A sync PostgreSQL engine needs psycopg or psycopg2 "
                "(pip install 'psycopg[binary]'), or set sync_url for this database."
            )
    else:
        driver = _SYNC_DRIVERS.get(driver, driver)
    drivername = f"{backend}+{driver}" if driver else backend
    return parsed.set(drivername=drivername).render_as_string(hide_password=False)


def engine_options(
    db: DatabaseConfig, *, is_async: bool, pool: str | None = None
) -> dict[str, Any]:
    """Keyword arguments for ``create_engine``/``create_async_engine``."""
    backend = db.backend
    options: dict[str, Any] = {}
    if backend != "sqlite":
        options["pool_pre_ping"] = True  # drop dead connections instead of failing a request
    if backend in ("mysql", "mariadb"):
        options["pool_recycle"] = 3600  # stay under MySQL's wait_timeout
    options.update(db.engine_options)

    kind = pool or db.pool or "auto"
    if kind == "auto" and is_memory_sqlite(db.url):
        kind = "static"  # every connection must see the same in-memory database
    if kind == "auto":
        return options
    if kind == "queue":
        options["poolclass"] = AsyncAdaptedQueuePool if is_async else QueuePool
        return options
    if kind == "null":
        options["poolclass"] = NullPool
    elif kind == "static":
        options["poolclass"] = StaticPool
    elif kind == "single":
        if is_async:
            raise ConfigError(f"Database {db.name!r}: pool 'single' is only for sync engines.")
        options["poolclass"] = SingletonThreadPool
    for key in _QUEUE_ONLY - ({"pool_size"} if kind == "single" else set()):
        options.pop(key, None)
    if kind in ("null", "static"):
        options.pop("pool_recycle", None)
    return options


def build_async_engine(db: DatabaseConfig, *, pool: str | None = None) -> AsyncEngine:
    return create_async_engine(db.url, **engine_options(db, is_async=True, pool=pool))


def build_sync_engine(db: DatabaseConfig, *, pool: str | None = None) -> Engine:
    url = db.sync_url or to_sync_url(db.url)
    options = engine_options(db, is_async=False, pool=pool)
    if is_memory_sqlite(url):
        options.setdefault("connect_args", {}).setdefault("check_same_thread", False)
    return create_engine(url, **options)


# -- database creation -------------------------------------------------------

_SERVER_DATABASE = {
    "postgresql": "postgres",
    "mssql": "master",
    "mysql": "information_schema",
    "mariadb": "information_schema",
}
_EXISTS_SQL = {
    "postgresql": "SELECT 1 FROM pg_database WHERE datname = :name",
    "mysql": "SELECT 1 FROM information_schema.schemata WHERE schema_name = :name",
    "mariadb": "SELECT 1 FROM information_schema.schemata WHERE schema_name = :name",
    "mssql": "SELECT 1 FROM sys.databases WHERE name = :name",
}


async def ensure_database(db: DatabaseConfig) -> bool:
    """Create the database named in the URL if it doesn't exist. ``True`` if created.

    Supported on PostgreSQL, MySQL/MariaDB, SQL Server and SQLite (creates the folder).
    Other backends (e.g. Oracle) are left alone.
    """
    url = make_url(db.url)
    backend = url.get_backend_name()
    name = url.database

    if backend == "sqlite":
        if name and name != ":memory:" and not name.startswith("file:"):
            path = Path(name)
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                return True
        return False
    if not name or backend not in _EXISTS_SQL:
        return False

    server = url.set(database=_SERVER_DATABASE[backend])
    engine = create_async_engine(server, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            exists = await conn.execute(text(_EXISTS_SQL[backend]), {"name": name})
            if exists.scalar() is not None:
                return False
            quoted = conn.dialect.identifier_preparer.quote(name)
            await conn.execute(text(f"CREATE DATABASE {quoted}"))
            return True
    finally:
        await engine.dispose()
