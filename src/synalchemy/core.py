"""The :class:`SynAlchemy` entry point."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, MetaData, Table, literal, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, sessionmaker

from synalchemy.config import DEFAULT_DB, Config, DatabaseConfig
from synalchemy.engines import (
    build_async_engine,
    build_sync_engine,
    ensure_database,
    is_memory_sqlite,
)
from synalchemy.exceptions import ConfigError
from synalchemy.model import Model, db_name_of
from synalchemy.session import RoutingSession

if TYPE_CHECKING:
    from synalchemy.migrations.runner import Migrator


class SynAlchemy:
    """Owns the engines, the routing session factories, and the per-database metadata.

    Engines are created lazily, the first time a database is used::

        db = SynAlchemy({"default": "postgresql://...", "analytics": "sqlite:///a.db"})
        async with db.session() as session:      # async engines
            ...
        with db.sync_session() as session:       # sync engines (scripts, Celery, ...)
            ...
    """

    def __init__(
        self,
        databases: Mapping[str, str | Mapping[str, Any] | DatabaseConfig] | None = None,
        *,
        config: Config | None = None,
        metadata: MetaData | None = None,
        session_options: Mapping[str, Any] | None = None,
    ) -> None:
        if config is None:
            if databases is None:
                raise ConfigError(
                    "Pass databases=... or config=..., or use SynAlchemy.from_config()."
                )
            config = Config(databases=dict(databases))  # type: ignore[arg-type]
        elif databases is not None:
            raise ConfigError("Pass either databases=... or config=..., not both.")

        self.config = config
        self.metadata = metadata if metadata is not None else Model.metadata
        self._engines: dict[str, AsyncEngine] = {}
        self._sync_engines: dict[str, Engine] = {}
        self._migration_engines: dict[str, AsyncEngine] = {}

        options = {"expire_on_commit": False, **(session_options or {})}
        async_routing = type(
            "AsyncRoutingSession",
            (RoutingSession,),
            {"_engine_for": staticmethod(lambda name: self.engine(name).sync_engine)},
        )
        sync_routing = type(
            "SyncRoutingSession", (RoutingSession,), {"_engine_for": staticmethod(self.sync_engine)}
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            sync_session_class=async_routing, **options
        )
        self.sync_sessionmaker: sessionmaker[Session] = sessionmaker(class_=sync_routing, **options)

    @classmethod
    def from_config(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        metadata: MetaData | None = None,
        session_options: Mapping[str, Any] | None = None,
        **overrides: Any,
    ) -> SynAlchemy:
        """Build from ``synalchemy.toml`` / ``pyproject.toml`` / environment variables."""
        return cls(
            config=Config.load(path, **overrides),
            metadata=metadata,
            session_options=session_options,
        )

    def __repr__(self) -> str:
        return f"SynAlchemy(databases={self.names!r})"

    # -- engines -------------------------------------------------------------

    @property
    def names(self) -> list[str]:
        """Configured database names, ``"default"`` first."""
        return [DEFAULT_DB, *(n for n in self.config.databases if n != DEFAULT_DB)]

    def engine(self, name: str = DEFAULT_DB) -> AsyncEngine:
        """Async engine for ``name``, created on first use."""
        engine = self._engines.get(name)
        if engine is None:
            engine = self._engines[name] = build_async_engine(self.config.database(name))
        return engine

    def sync_engine(self, name: str = DEFAULT_DB) -> Engine:
        """Sync engine for ``name`` (uses ``sync_url`` or the sync twin of the async driver)."""
        engine = self._sync_engines.get(name)
        if engine is None:
            engine = self._sync_engines[name] = build_sync_engine(self.config.database(name))
        return engine

    def migration_engine(self, name: str = DEFAULT_DB) -> AsyncEngine:
        """Unpooled async engine for migrations, so they never hold app connections.

        In-memory SQLite and ``pool = "static"`` share one connection by design, so the
        app engine itself is returned for them.
        """
        db = self.config.database(name)
        if db.pool == "static" or is_memory_sqlite(db.url):
            return self.engine(name)
        engine = self._migration_engines.get(name)
        if engine is None:
            engine = self._migration_engines[name] = build_async_engine(db, pool="null")
        return engine

    def pool_status(self) -> dict[str, str]:
        """Pool status of every engine created so far, keyed ``name`` / ``name (sync)``."""
        status = {name: e.pool.status() for name, e in self._engines.items()}
        status.update({f"{name} (sync)": e.pool.status() for name, e in self._sync_engines.items()})
        return status

    async def connect(self, *names: str) -> None:
        """Create missing databases (if configured) and check every engine can connect."""
        for name in names or self.names:
            db = self.config.database(name)
            if db.create_if_missing:
                await ensure_database(db)
            async with self.engine(name).connect() as conn:
                await conn.execute(select(literal(1)))

    async def dispose(self) -> None:
        """Close all pooled connections, async and sync. Engines are recreated on next use."""
        engines = [*self._engines.values(), *self._migration_engines.values()]
        sync_engines = list(self._sync_engines.values())
        self._engines, self._migration_engines, self._sync_engines = {}, {}, {}
        for engine in engines:
            await engine.dispose()
        for sync_engine in sync_engines:
            sync_engine.dispose()

    def dispose_sync(self) -> None:
        """Close the sync engines only (for code that never runs an event loop)."""
        sync_engines, self._sync_engines = self._sync_engines, {}
        for engine in sync_engines.values():
            engine.dispose()

    @asynccontextmanager
    async def lifespan(self, _app: Any = None) -> AsyncIterator[SynAlchemy]:
        """Connect on enter, dispose on exit. Works as a FastAPI/Starlette ``lifespan``."""
        await self.connect()
        try:
            yield self
        finally:
            await self.dispose()

    # -- sessions ------------------------------------------------------------

    def session(self, **kwargs: Any) -> AsyncSession:
        """New routing ``AsyncSession`` (use it as ``async with``)."""
        return self.sessionmaker(**kwargs)

    def sync_session(self, **kwargs: Any) -> Session:
        """New routing sync ``Session`` (use it as ``with``)."""
        return self.sync_sessionmaker(**kwargs)

    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """Async generator for dependency injection, e.g. ``Depends(db.get_session)``."""
        async with self.session() as session:
            yield session

    # -- metadata ------------------------------------------------------------

    def tables_for(self, name: str) -> list[Table]:
        """Tables of the shared metadata that belong to ``name``."""
        self.config.database(name)
        return [t for t in self.metadata.sorted_tables if db_name_of(t) == name]

    def metadata_for(self, name: str) -> MetaData:
        """A copy of the metadata holding only the tables of database ``name``."""
        self.check_models()
        metadata = MetaData(naming_convention=dict(self.metadata.naming_convention))
        for table in self.tables_for(name):
            for fk in table.foreign_keys:
                target = fk.column.table
                if db_name_of(target) != name:
                    raise ConfigError(
                        f"{table.name}.{fk.parent.name} references {target.name}, which lives "
                        f"in database {db_name_of(target)!r}. Foreign keys can't cross databases."
                    )
            table.to_metadata(metadata)
        return metadata

    def check_models(self) -> None:
        """Raise if any table names a database that isn't configured."""
        for table in self.metadata.sorted_tables:
            name = db_name_of(table)
            if name not in self.config.databases:
                raise ConfigError(
                    f"Table {table.name!r} uses __db_name__={name!r}, which isn't configured."
                )

    async def create_all(self, *names: str) -> None:
        """Create each database's tables directly (handy in tests; use migrations otherwise)."""
        for name in names or self.names:
            metadata = self.metadata_for(name)
            async with self.engine(name).begin() as conn:
                await conn.run_sync(metadata.create_all)

    async def drop_all(self, *names: str) -> None:
        """Drop the tables of each database."""
        for name in names or self.names:
            metadata = self.metadata_for(name)
            async with self.engine(name).begin() as conn:
                await conn.run_sync(metadata.drop_all)

    # -- migrations ----------------------------------------------------------

    def migrator(self, name: str = DEFAULT_DB) -> Migrator:
        """Return the migration runner for database ``name``."""
        from synalchemy.migrations.runner import Migrator

        return Migrator(self, name)
