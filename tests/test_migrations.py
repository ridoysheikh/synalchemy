from __future__ import annotations

import pytest
import sqlalchemy as sa

from synalchemy import ChainError, Config, SynAlchemy
from synalchemy.migrations import naming

from .conftest import build_models


async def table_names(db: SynAlchemy, name: str) -> set[str]:
    async with db.engine(name).connect() as conn:
        return set(await conn.run_sync(lambda c: sa.inspect(c).get_table_names()))


async def column_names(db: SynAlchemy, name: str, table: str) -> set[str]:
    async with db.engine(name).connect() as conn:
        cols = await conn.run_sync(lambda c: sa.inspect(c).get_columns(table))
        return {c["name"] for c in cols}


async def test_full_lifecycle_on_two_databases(make_db, sqlite_config: Config) -> None:
    db = make_db(build_models(1))
    try:
        # initial revisions: one per database, in its own folder
        paths = {n: await db.migrator(n).make_revision("initial") for n in db.names}
        assert paths["default"].parent.name == "default"
        assert paths["analytics"].parent.name == "analytics"
        assert "db_name = 'analytics'" in paths["analytics"].read_text()

        for name in db.names:
            result = await db.migrator(name).upgrade()
            assert len(result.steps) == 1
        assert await table_names(db, "default") == {
            "users",
            "synalchemy_version",
        }
        assert "events" in await table_names(db, "analytics")
        assert "users" not in await table_names(db, "analytics")

        # nothing changed -> no file
        assert await db.migrator("default").make_revision("noop") is None
    finally:
        await db.dispose()

    # models change: new column in default, new table in analytics
    db = make_db(build_models(2))
    try:
        second = await db.migrator("default").make_revision("add email")
        assert second is not None
        text = second.read_text()
        assert "add_column" in text
        assert f"down_revision = {paths['default'].name[:21]!r}" in text
        assert await db.migrator("analytics").make_revision("add sessions") is not None

        for name in db.names:
            await db.migrator(name).upgrade()
        assert "email" in await column_names(db, "default", "users")
        assert "sessions" in await table_names(db, "analytics")

        status = await db.migrator("default").status()
        assert status.pending == 0 and status.current == status.head

        # down one, back up, then down two
        migrator = db.migrator("default")
        down = await migrator.downgrade(1)
        assert [d for _, d in down.steps] == ["down"]
        assert "email" not in await column_names(db, "default", "users")
        up = await migrator.upgrade()
        assert [d for _, d in up.steps] == ["up"]
        assert "email" in await column_names(db, "default", "users")
        await migrator.downgrade(2)
        assert "users" not in await table_names(db, "default")
        assert (await migrator.upgrade("base")).changed is False

        # straight to head and back to base
        await migrator.goto("head")
        assert len(await migrator.history()) == 2
        await migrator.goto("base")
        assert await migrator.current() is None
    finally:
        await db.dispose()


async def test_hand_written_sync_and_async_revisions(make_db) -> None:
    db = make_db(build_models(1))
    migrator = db.migrator("default")
    try:
        await migrator.make_revision("initial")
        await migrator.upgrade()
        sync_rev = await migrator.make_revision("seed", empty=True)
        sync_rev.write_text(
            sync_rev.read_text()
            .replace(
                "def upgrade() -> None:\n    pass",
                "def upgrade() -> None:\n"
                "    op.execute(\"INSERT INTO users (id, name) VALUES (1, 'sync')\")\n"
                "    run_async(_seed)\n\n\n"
                "async def _seed(conn):\n"
                "    await conn.execute(\n"
                "        sa.text(\"INSERT INTO users (id, name) VALUES (2, 'async')\"))",
            )
            .replace(
                "def downgrade() -> None:\n    pass",
                "def downgrade() -> None:\n    op.execute('DELETE FROM users')",
            )
        )
        async_rev = await migrator.make_revision("async seed", empty=True, use_async=True)
        assert "async def upgrade()" in async_rev.read_text()
        async_rev.write_text(
            async_rev.read_text()
            .replace(
                "async def upgrade() -> None:\n    pass",
                "async def upgrade() -> None:\n"
                "    await aop.add_column('users', sa.Column('score', sa.Integer()))\n"
                "    await get_connection().execute(sa.text('UPDATE users SET score = 7'))",
            )
            .replace(
                "async def downgrade() -> None:\n    pass",
                "async def downgrade() -> None:\n    await aop.drop_column('users', 'score')",
            )
        )
        await migrator.upgrade()
        async with db.session() as session:
            rows = (
                await session.execute(sa.text("SELECT name, score FROM users ORDER BY id"))
            ).all()
        assert rows == [("sync", 7), ("async", 7)]

        await migrator.downgrade(2)
        assert "score" not in await column_names(db, "default", "users")
        async with db.session() as session:
            assert (await session.execute(sa.text("SELECT count(*) FROM users"))).scalar() == 0
    finally:
        await db.dispose()


async def test_failed_revision_rolls_back_and_reports(make_db) -> None:
    db = make_db(build_models(1))
    migrator = db.migrator("default")
    try:
        await migrator.make_revision("initial")
        bad = await migrator.make_revision("bad", empty=True)
        bad.write_text(
            bad.read_text().replace(
                "def upgrade() -> None:\n    pass",
                "def upgrade() -> None:\n    op.execute('SELECT * FROM no_such_table')",
            )
        )
        from synalchemy import MigrationError

        with pytest.raises(MigrationError, match="no_such_table"):
            await migrator.upgrade()
        status = await migrator.status()
        assert status.pending == 1  # first one applied, bad one not
        assert len((await migrator.downgrade(1)).steps) == 1
    finally:
        await db.dispose()


async def test_broken_chain_blocks_migrate(make_db) -> None:
    db = make_db(build_models(1))
    migrator = db.migrator("default")
    try:
        first = await migrator.make_revision("initial")
        rev = first.name[:21]
        naming.write_revision(
            migrator.directory,
            revision="20990101T000000Z_aaaa",
            message="a",
            down_revision=rev,
            db_name="default",
        )
        naming.write_revision(
            migrator.directory,
            revision="20990101T000001Z_bbbb",
            message="b",
            down_revision=rev,
            db_name="default",
        )
        with pytest.raises(ChainError, match="several children"):
            await migrator.upgrade()
        changes = migrator.chain.rechain(None)
        assert len(changes) == 1
        assert len((await migrator.upgrade()).steps) == 3
    finally:
        await db.dispose()


async def test_make_refuses_when_database_is_behind(make_db) -> None:
    db = make_db(build_models(1))
    migrator = db.migrator("default")
    try:
        await migrator.make_revision("initial")
        from synalchemy import MigrationError

        with pytest.raises(MigrationError, match="Run `migrate` first"):
            await migrator.make_revision("again")
    finally:
        await db.dispose()


async def test_offline_sql(make_db) -> None:
    db = make_db(build_models(1))
    migrator = db.migrator("default")
    try:
        await migrator.make_revision("initial")
    finally:
        await db.dispose()
    sql = migrator.sql()
    assert "CREATE TABLE IF NOT EXISTS synalchemy_version" in sql
    assert "CREATE TABLE users" in sql
    assert "INSERT INTO synalchemy_version" in sql


class Vector(sa.types.UserDefinedType):
    """Stand-in for a third-party column type such as pgvector's ``Vector``."""

    cache_ok = True

    def __init__(self, dim: int) -> None:
        self.dim = dim

    def get_col_spec(self, **kw) -> str:
        return f"VECTOR({self.dim})"


async def test_revision_with_third_party_column_type(make_db) -> None:
    metadata = sa.MetaData()
    sa.Table("docs", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table(
        "chunks",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("embedding", Vector(3)),
    )
    db = make_db(metadata)
    try:
        path = await db.migrator("default").make_revision("vectors")
        assert path is not None
        text = path.read_text()
        assert "Vector(" in text
        assert f"import {__name__}" in text
        await db.migrator("default").upgrade()
        assert "embedding" in await column_names(db, "default", "chunks")
    finally:
        await db.dispose()
