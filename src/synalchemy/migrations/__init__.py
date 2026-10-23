"""Helpers imported by revision files.

Sync revisions (the default) use ``op``, exactly like Alembic. They still run on the
async driver, inside ``AsyncConnection.run_sync()``::

    def upgrade() -> None:
        op.add_column("users", sa.Column("age", sa.Integer()))
        run_async(backfill_ages)            # await async code from a sync revision

    async def backfill_ages(conn: AsyncConnection) -> None:
        await conn.execute(sa.text("UPDATE users SET age = 0"))

Async revisions (``migrations make --async``) use ``aop``, the awaitable mirror of ``op``::

    async def upgrade() -> None:
        await aop.add_column("users", sa.Column("age", sa.Integer()))
        await get_connection().execute(sa.text("UPDATE users SET age = 0"))
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypeVar

from alembic import op
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql.elements import conv
from sqlalchemy.util import await_only

from synalchemy.migrations import enums as enums  # registers the ENUM operations

T = TypeVar("T")

ASYNC_CONNECTION_KEY = "synalchemy.async_connection"
_current_connection: ContextVar[AsyncConnection | None] = ContextVar(
    "synalchemy_migration_connection", default=None
)


def get_connection() -> AsyncConnection:
    """The ``AsyncConnection`` running the current revision."""
    conn = _current_connection.get()
    if conn is None:
        bind = op.get_bind() if _inside_sync_revision() else None
        conn = bind.info.get(ASYNC_CONNECTION_KEY) if bind is not None else None
    if conn is None:
        raise RuntimeError("get_connection() only works while a revision is running.")
    return conn


def run_async(fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    """From a sync ``upgrade()``/``downgrade()``, await ``fn(conn, *args, **kwargs)``."""
    return await_only(fn(get_connection(), *args, **kwargs))


def _inside_sync_revision() -> bool:
    try:
        op.get_context()
    except (NameError, AttributeError):
        return False
    return True


class AsyncOperations:
    """Awaitable version of ``op`` for ``async def upgrade()`` revisions.

    ``await aop.<name>(...)`` runs ``op.<name>(...)`` on the current connection.
    ``aop.f()`` and ``aop.inline_literal()`` stay synchronous, as they only build values.
    """

    @staticmethod
    def f(name: str) -> conv:
        return conv(name)

    @staticmethod
    def inline_literal(value: Any, type_: Any = None) -> Any:
        return Operations.inline_literal(value, type_)

    def __getattr__(self, name: str) -> Callable[..., Awaitable[Any]]:
        if name.startswith("_"):
            raise AttributeError(name)

        async def call(*args: Any, **kwargs: Any) -> Any:
            def run(sync_conn: Any) -> Any:
                operations = Operations(MigrationContext.configure(connection=sync_conn))
                return getattr(operations, name)(*args, **kwargs)

            return await get_connection().run_sync(run)

        call.__name__ = name
        return call


aop = AsyncOperations()

__all__ = ["AsyncOperations", "aop", "get_connection", "op", "run_async"]
