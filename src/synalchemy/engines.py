"""Engine construction: async and sync engines, pool selection, database creation.

Pool kinds (``pool = "..."`` per database or in ``engine_defaults``):

========== ============================== =============================================
kind       pool class                     use it for
========== ============================== =============================================
``auto``   dialect default; NullPool on   most apps (default)
           serverless platforms
``queue``  QueuePool / AsyncAdaptedQueue  long-running servers; tune ``pool_size`` etc.
``null``   NullPool                       CLIs, scripts, serverless
``external`` NullPool, no prepared-       behind a transaction pooler (PgBouncer,
           statement cache                Supabase / Neon poolers, RDS Proxy)
``static`` StaticPool                     one shared connection (in-memory SQLite, tests)
``single`` SingletonThreadPool (sync)     one connection per thread
========== ============================== =============================================

Queue-only options (``pool_size``, ``max_overflow``, ...) are dropped automatically for
pools that don't accept them, so switching ``pool`` never breaks the config.
"""

from __future__ import annotations

import importlib.util
import os
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

POOL_KINDS = ("auto", "queue", "null", "external", "static", "single")

# Set by serverless platforms, where an instance may freeze between requests: a pool's
# idle connections would go stale, so ``auto`` opens one connection per checkout instead.
SERVERLESS_ENV = (
    "AWS_LAMBDA_FUNCTION_NAME",  # AWS Lambda
    "VERCEL",  # Vercel functions
    "NETLIFY",  # Netlify functions
    "FUNCTION_TARGET",  # Google Cloud Functions
    "FUNCTIONS_WORKER_RUNTIME",  # Azure Functions
)

# A transaction pooler hands each transaction a different server connection, so the
# driver must not keep prepared statements between them.
_NO_PREPARED_STATEMENTS = {
    "asyncpg": {"statement_cache_size": 0, "prepared_statement_cache_size": 0},
    "psycopg": {"prepare_threshold": None},
    "psycopg_async": {"prepare_threshold": None},
}

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


def is_serverless() -> bool:
    """``True`` on a serverless platform (see ``SERVERLESS_ENV``)."""
    return any(os.environ.get(name) for name in SERVERLESS_ENV)


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
    db: DatabaseConfig, *, is_async: bool, pool: str | None = None, url: str | None = None
) -> dict[str, Any]:
    """Keyword arguments for ``create_engine``/``create_async_engine``."""
    url = url or db.url
    backend = make_url(url).get_backend_name()
    options: dict[str, Any] = {}
    if backend != "sqlite":
        options["pool_pre_ping"] = True  # drop dead connections instead of failing a request
    if backend in ("mysql", "mariadb"):
        options["pool_recycle"] = 3600  # stay under MySQL's wait_timeout
    options.update(db.engine_options)

    kind = pool or db.pool or "auto"
    if kind == "auto" and is_memory_sqlite(url):
        kind = "static"  # every connection must see the same in-memory database
    if kind == "auto" and is_serverless():
        kind = "null"
    if kind == "auto":
        return options
    if kind == "external":
        driver = make_url(url).drivername.partition("+")[2]
        settings = _NO_PREPARED_STATEMENTS.get(driver)
        if settings:
            options["connect_args"] = {**settings, **options.get("connect_args", {})}
        kind = "null"
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


def build_migration_engine(db: DatabaseConfig) -> AsyncEngine:
    """Unpooled engine for migrations, on ``migration_url`` when set.

    Without a ``migration_url``, a database behind a transaction pooler keeps the
    ``external`` driver settings. Note that ``migrate``'s lock is held for the whole
    session, so a transaction pooler can't guarantee it: prefer a direct ``migration_url``.
    """
    if db.migration_url:
        url = db.migration_url
        options = engine_options(db, is_async=True, pool="null", url=url)
    else:
        url = db.url
        pool = "external" if db.pool == "external" else "null"
        options = engine_options(db, is_async=True, pool=pool)
    return create_async_engine(url, **options)


def build_sync_engine(db: DatabaseConfig, *, pool: str | None = None) -> Engine:
    url = db.sync_url or to_sync_url(db.url)
    options = engine_options(db, is_async=False, pool=pool, url=url)
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
