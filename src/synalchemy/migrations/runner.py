"""Applying and reverting revisions on one database."""

from __future__ import annotations

import inspect as pyinspect
import io
import zlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Column, MetaData, String, Table, delete, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.schema import CreateTable

from synalchemy.engines import ensure_database
from synalchemy.exceptions import MigrationError
from synalchemy.migrations import ASYNC_CONNECTION_KEY, _current_connection, autogen, naming
from synalchemy.migrations.chain import UP, Chain, Revision

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from synalchemy.core import SynAlchemy

# Session-level locks so two `migrate` processes can't run on the same database at once.
# Each entry: (acquire SQL, release SQL); :key is an int, :name a string.
_LOCKS = {
    "postgresql": ("SELECT pg_advisory_lock(:key)", "SELECT pg_advisory_unlock(:key)"),
    # MariaDB rejects a negative (infinite) timeout, so wait up to a day instead
    "mysql": ("SELECT GET_LOCK(:name, 86400)", "SELECT RELEASE_LOCK(:name)"),
    "mariadb": ("SELECT GET_LOCK(:name, 86400)", "SELECT RELEASE_LOCK(:name)"),
    "mssql": (
        "EXEC sp_getapplock @Resource = :name, @LockMode = 'Exclusive', "
        "@LockOwner = 'Session', @LockTimeout = -1",
        "EXEC sp_releaseapplock @Resource = :name, @LockOwner = 'Session'",
    ),
}


@dataclass
class MoveResult:
    """What a migrate command did to one database."""

    db_name: str
    from_rev: str | None
    to_rev: str | None
    steps: list[tuple[Revision, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.steps)


@dataclass
class Status:
    db_name: str
    current: str | None
    head: str | None
    pending: int


def version_table(name: str) -> Table:
    return Table(name, MetaData(), Column("version_num", String(64), primary_key=True))


class Migrator:
    """Runs revisions for one database. Get one with ``SynAlchemy.migrator(name)``."""

    def __init__(self, db: SynAlchemy, name: str) -> None:
        self.db = db
        self.name = name
        self.database = db.config.database(name)
        self.directory: Path = db.config.migrations_path / name
        self.version_table = version_table(db.config.version_table)

    @property
    def chain(self) -> Chain:
        """Revision files, re-read on every access."""
        return Chain.load(self.name, self.directory)

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self.database.create_if_missing:
            await ensure_database(self.database)
        async with self.db.migration_engine(self.name).connect() as conn:
            yield conn

    # -- reading state -------------------------------------------------------

    def _read_version(self, conn: Connection) -> str | None:
        if not inspect(conn).has_table(self.version_table.name):
            return None
        return conn.execute(select(self.version_table.c.version_num)).scalar()

    async def current(self) -> str | None:
        async with self.connect() as conn:
            return await conn.run_sync(self._read_version)

    async def status(self) -> Status:
        chain = self.chain
        current = await self.current()
        head = chain.head
        return Status(self.name, current, head, len(chain.steps(current, head)))

    async def history(self) -> list[tuple[Revision, bool]]:
        """Revisions base to head, with whether each one is applied."""
        chain = self.chain
        chain.validate()
        applied_upto = chain.index(await self.current())
        return [(rev, i <= applied_upto) for i, rev in enumerate(chain.ordered)]

    # -- moving --------------------------------------------------------------

    async def upgrade(self, target: str = "head") -> MoveResult:
        """Apply revisions up to ``target`` (``head`` by default)."""
        return await self._move(lambda chain, current: chain.resolve(target))

    async def downgrade(self, steps: int = 1) -> MoveResult:
        """Revert the last ``steps`` applied revisions."""
        return await self._move(lambda chain, current: chain.target_down(current, steps))

    async def goto(self, target: str) -> MoveResult:
        """Move up or down to ``target`` (a revision id or prefix, ``head`` or ``base``)."""
        return await self._move(lambda chain, current: chain.resolve(target))

    async def _move(self, resolve: Callable[[Chain, str | None], str | None]) -> MoveResult:
        chain = self.chain
        chain.validate()
        async with self.connect() as conn, self._lock(conn):
            async with conn.begin():
                await conn.run_sync(self.version_table.metadata.create_all)
            async with conn.begin():
                current = await conn.run_sync(self._read_version)
            target = resolve(chain, current)
            result = MoveResult(self.name, current, target, chain.steps(current, target))
            for revision, direction in result.steps:
                async with conn.begin():
                    await self._apply(conn, revision, direction)
            return result

    async def _apply(self, conn: AsyncConnection, revision: Revision, direction: str) -> None:
        fn = revision.function(direction)
        new_version = revision.id if direction == UP else revision.down
        sync_conn = conn.sync_connection
        assert sync_conn is not None
        sync_conn.info[ASYNC_CONNECTION_KEY] = conn
        token = _current_connection.set(conn)
        try:
            if pyinspect.iscoroutinefunction(fn):
                await fn()
            else:
                await conn.run_sync(self._run_sync_revision, fn)
            await conn.run_sync(self._write_version, new_version)
        except Exception as exc:
            raise MigrationError(
                f"{self.name}: {direction}grade of {revision.id} ({revision.path.name}) "
                f"failed: {exc}"
            ) from exc
        finally:
            _current_connection.reset(token)
            sync_conn.info.pop(ASYNC_CONNECTION_KEY, None)

    @staticmethod
    def _run_sync_revision(conn: Connection, fn: Callable[[], Any]) -> None:
        operations = Operations(MigrationContext.configure(connection=conn))
        operations._install_proxy()
        try:
            fn()
        finally:
            operations._remove_proxy()

    def _write_version(self, conn: Connection, version: str | None) -> None:
        conn.execute(delete(self.version_table))
        if version is not None:
            conn.execute(insert(self.version_table).values(version_num=version))

    @asynccontextmanager
    async def _lock(self, conn: AsyncConnection) -> AsyncIterator[None]:
        sql = _LOCKS.get(conn.dialect.name)
        if sql is None:
            yield
            return
        acquire, release = sql
        name = f"synalchemy:{self.version_table.name}"
        params = {"key": zlib.crc32(name.encode()), "name": name}
        async with conn.begin():
            granted = await conn.execute(text(acquire), params)
            if conn.dialect.name in ("mysql", "mariadb") and granted.scalar() != 1:
                raise MigrationError(f"{self.name}: couldn't get the migration lock {name!r}.")
        try:
            yield
        finally:
            if conn.in_transaction():
                await conn.rollback()
            async with conn.begin():
                await conn.execute(text(release), params)

    # -- generating ----------------------------------------------------------

    async def make_revision(
        self, message: str, *, empty: bool = False, use_async: bool = False
    ) -> Path | None:
        """Write a new revision file. Returns ``None`` when the models match the database."""
        chain = self.chain
        head = chain.head
        upgrades = downgrades = "pass"
        imports = ""
        if not empty:
            async with self.connect() as conn:
                current = await conn.run_sync(self._read_version)
                if current != head:
                    raise MigrationError(
                        f"{self.name}: database is at {current or '<base>'} but the latest "
                        f"revision is {head}. Run `migrate` first so the diff is accurate."
                    )
                rendered = await conn.run_sync(autogen.render_diff, self.db, self.name, use_async)
            if rendered is None:
                return None
            upgrades, downgrades, imports = rendered
        return naming.write_revision(
            self.directory,
            revision=naming.new_revision_id(after=head),
            message=message,
            down_revision=head,
            db_name=self.name,
            upgrades=upgrades,
            downgrades=downgrades,
            imports=imports,
            use_async=use_async,
        )

    async def pending_changes(self) -> bool:
        """``True`` when the models differ from the database."""
        async with self.connect() as conn:
            return await conn.run_sync(autogen.render_diff, self.db, self.name) is not None

    # -- offline -------------------------------------------------------------

    def sql(self, from_ref: str | None = None, to_ref: str = "head") -> str:
        """Render the SQL for moving ``from_ref`` -> ``to_ref`` without connecting."""
        chain = self.chain
        start, target = chain.resolve(from_ref), chain.resolve(to_ref)
        buffer = io.StringIO()
        context = MigrationContext.configure(
            dialect_name=make_url(self.database.url).get_backend_name(),
            opts={"as_sql": True, "output_buffer": buffer, "literal_binds": True},
        )
        operations = Operations(context)
        operations._install_proxy()
        try:
            if start is None:
                operations.execute(CreateTable(self.version_table, if_not_exists=True))
            for revision, direction in chain.steps(start, target):
                fn = revision.function(direction)
                if pyinspect.iscoroutinefunction(fn):
                    raise MigrationError(
                        f"{revision.path.name} is an async revision; offline SQL needs sync ones."
                    )
                buffer.write(f"\n-- {direction}: {revision.id} {revision.message}\n")
                fn()
                new_version = revision.id if direction == UP else revision.down
                operations.execute(delete(self.version_table))
                if new_version is not None:
                    operations.execute(insert(self.version_table).values(version_num=new_version))
        finally:
            operations._remove_proxy()
        return buffer.getvalue()
