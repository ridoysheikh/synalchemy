"""The same migration lifecycle on every dialect a test URL is configured for.

Set any of: SYNALCHEMY_TEST_PG_URL, SYNALCHEMY_TEST_MYSQL_URL, SYNALCHEMY_TEST_MARIADB_URL,
SYNALCHEMY_TEST_MSSQL_URL, SYNALCHEMY_TEST_ORACLE_URL. SQLite always runs.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from synalchemy import Config, DBNameMixin, SynAlchemy
from synalchemy.config import to_async_url

ENV = {
    "postgresql": "SYNALCHEMY_TEST_PG_URL",
    "mysql": "SYNALCHEMY_TEST_MYSQL_URL",
    "mariadb": "SYNALCHEMY_TEST_MARIADB_URL",
    "mssql": "SYNALCHEMY_TEST_MSSQL_URL",
    "oracle": "SYNALCHEMY_TEST_ORACLE_URL",
}
URLS = {"sqlite": "sqlite:///{tmp}/dialect.db", **{k: os.environ.get(v) for k, v in ENV.items()}}
CAN_CREATE = {"postgresql", "mysql", "mariadb", "mssql"}
INLINE_ENUM = {"mysql", "mariadb"}
LOCKED = {"postgresql", "mysql", "mariadb", "mssql"}


def models(values: list[str], *, nickname: bool = False) -> sa.MetaData:
    class Base(DBNameMixin, DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False)
        name: Mapped[str] = mapped_column(sa.String(50))
        role: Mapped[str] = mapped_column(sa.Enum(*values, name="user_role"))
        if nickname:
            nick: Mapped[str | None] = mapped_column(sa.String(30))

    return Base.metadata


@pytest.fixture(params=list(URLS))
async def dialect(request, tmp_path: Path) -> AsyncIterator[tuple[str, Config]]:
    kind, url = request.param, URLS[request.param]
    if not url:
        pytest.skip(f"set {ENV[kind]} to test {kind}")
    url = url.format(tmp=tmp_path)
    parsed = make_url(url)
    dbname = None
    if kind in CAN_CREATE:
        dbname = f"syn_{uuid.uuid4().hex[:8]}"
        url = parsed.set(database=dbname).render_as_string(hide_password=False)
    config = Config(
        databases={"default": {"url": url, "create_if_missing": kind in CAN_CREATE}},
        root=tmp_path,
    )
    yield kind, config

    if dbname:
        server = {"postgresql": "postgres", "mssql": "master"}.get(kind)
        admin = create_async_engine(
            to_async_url(parsed.set(database=server).render_as_string(hide_password=False)),
            isolation_level="AUTOCOMMIT",
        )
        async with admin.connect() as conn:
            force = " WITH (FORCE)" if kind == "postgresql" else ""
            quoted = conn.dialect.identifier_preparer.quote(dbname)
            await conn.execute(sa.text(f"DROP DATABASE IF EXISTS {quoted}{force}"))
        await admin.dispose()
    elif kind == "oracle":
        engine = create_async_engine(to_async_url(url))
        async with engine.begin() as conn:
            for table in ("users", "synalchemy_version"):
                await conn.execute(
                    sa.text(
                        "BEGIN EXECUTE IMMEDIATE 'DROP TABLE "
                        f"{table} PURGE'; EXCEPTION WHEN OTHERS THEN NULL; END;"
                    )
                )
        await engine.dispose()


async def test_lifecycle(dialect: tuple[str, Config]) -> None:
    kind, config = dialect

    async def revision(metadata: sa.MetaData, message: str) -> str | None:
        db = SynAlchemy(config=config, metadata=metadata)
        try:
            path = await db.migrator().make_revision(message)
            await db.migrator().upgrade()
            return path.read_text() if path else None
        finally:
            await db.dispose()

    first = await revision(models(["admin", "member"]), "initial")
    assert first and "create_table('users'" in first

    db = SynAlchemy(config=config, metadata=models(["admin", "member"]))
    try:
        users = db.metadata.tables["users"]
        # sync engine, sync driver
        with db.sync_session() as session:
            session.execute(sa.insert(users).values(id=1, name="ada", role="member"))
            session.commit()
        # async engine reads it back
        async with db.session() as session:
            assert (await session.execute(sa.select(users.c.role))).scalar() == "member"
    finally:
        await db.dispose()

    second = await revision(models(["admin", "member", "guest"], nickname=True), "guest + nick")
    assert second and "add_column(" in second and "'nick'" in second
    if kind in INLINE_ENUM:
        assert "alter_column('users', 'role'" in second
        assert "'guest'" in second
    if kind == "postgresql":
        assert "sync_enum_values('user_role'" in second

    final = ["admin", "member", "guest"]
    if kind in INLINE_ENUM:
        final = ["member", "admin", "guest"]  # order matters for inline ENUMs
        reordered = await revision(models(final, nickname=True), "reorder enum")
        assert reordered and "alter_column('users', 'role'" in reordered

    db = SynAlchemy(config=config, metadata=models(final, nickname=True))
    try:
        users = db.metadata.tables["users"]
        async with db.session() as session:
            await session.execute(sa.insert(users).values(id=2, name="bo", role="guest"))
            await session.commit()

        migrator = db.migrator()
        assert await migrator.make_revision("noop") is None
        if kind in LOCKED:
            # two concurrent `migrate` runs: the lock makes the second one see it's done
            await migrator.make_revision("no-op", empty=True)
            results = await asyncio.gather(migrator.upgrade(), db.migrator().upgrade())
            assert sorted(len(r.steps) for r in results) == [0, 1]

        assert "CREATE TABLE" in migrator.sql().upper()

        async with db.session() as session:
            await session.execute(sa.delete(users))  # removing ENUM values in use must fail
            await session.commit()
        await migrator.goto("base")
        async with db.migration_engine().connect() as conn:
            names = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
        assert "users" not in names
    finally:
        await db.dispose()
