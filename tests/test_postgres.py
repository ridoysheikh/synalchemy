"""PostgreSQL-only behaviour: ENUM sync, database auto-creation, advisory locking."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from synalchemy import Config, DBNameMixin, MigrationError, SynAlchemy

from .conftest import build_models

pytestmark = pytest.mark.postgres


def enum_models(values: list[str], *, with_table: bool = True) -> sa.MetaData:
    class Base(DBNameMixin, DeclarativeBase):
        pass

    if with_table:

        class User(Base):
            __tablename__ = "users"
            id: Mapped[int] = mapped_column(primary_key=True)
            role: Mapped[str] = mapped_column(
                sa.Enum(*values, name="user_role"), server_default=sa.text(f"'{values[0]}'")
            )
            tags: Mapped[list[str] | None] = mapped_column(
                postgresql.ARRAY(sa.Enum(*values, name="user_role"))
            )

    class Event(Base):
        __tablename__ = "events"
        __db_name__ = "analytics"
        id: Mapped[int] = mapped_column(primary_key=True)

    return Base.metadata


async def labels(db: SynAlchemy) -> list[str] | None:
    async with db.engine().connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'user_role' ORDER BY e.enumsortorder"
            )
        )
        found = [r[0] for r in rows]
        return found or None


async def scalar(db: SynAlchemy, sql: str):
    async with db.engine().connect() as conn:
        return (await conn.execute(sa.text(sql))).scalar()


async def test_enum_lifecycle(pg_config: Config) -> None:
    async def step(values: list[str] | None, message: str) -> Path | None:
        metadata = enum_models(values or ["x"], with_table=values is not None)
        db = SynAlchemy(config=pg_config, metadata=metadata)
        try:
            await db.migrator().upgrade()
            path = await db.migrator().make_revision(message)
            await db.migrator().upgrade()
            return path
        finally:
            await db.dispose()

    db = SynAlchemy(config=pg_config, metadata=sa.MetaData())
    try:
        first = await step(["admin", "member"], "initial")
        assert "op.create_enum('user_role', ['admin', 'member'])" in first.read_text()
        assert "create_type=False" in first.read_text()
        assert await labels(db) == ["admin", "member"]
        async with db.engine().begin() as conn:
            await conn.execute(
                sa.text("INSERT INTO users (id, role, tags) VALUES (1, 'member', '{member,admin}')")
            )

        added = await step(["admin", "member", "guest"], "add guest")
        text = added.read_text()
        assert (
            "sync_enum_values('user_role', ['admin', 'member'], ['admin', 'member', 'guest'])"
            in text
        )
        assert "alter_column" not in text
        assert await labels(db) == ["admin", "member", "guest"]

        # remove "member" with a rename so the existing row is converted
        db2 = SynAlchemy(config=pg_config, metadata=enum_models(["guest", "admin"]))
        try:
            removed = await db2.migrator().make_revision("drop member")
        finally:
            await db2.dispose()
        removed.write_text(
            removed.read_text().replace(
                "['guest', 'admin'])", "['guest', 'admin'], renames={'member': 'guest'})", 1
            )
        )
        db2 = SynAlchemy(config=pg_config, metadata=enum_models(["guest", "admin"]))
        try:
            await db2.migrator().upgrade()
        finally:
            await db2.dispose()
        assert await labels(db) == ["guest", "admin"]
        assert await scalar(db, "SELECT role::text FROM users") == "guest"
        assert await scalar(db, "SELECT tags::text FROM users") == "{guest,admin}"
        assert "'admin'::user_role" in await scalar(
            db,
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'role'",
        )

        # revert the removal: values come back; converted rows stay valid as "guest"
        await db.migrator().downgrade(1)
        assert await labels(db) == ["admin", "member", "guest"]
        assert await scalar(db, "SELECT role::text FROM users") == "guest"

        # without a rename, removing a value in use fails and rolls back
        async with db.engine().begin() as conn:
            await conn.execute(sa.text("UPDATE users SET role = 'guest'"))
        with pytest.raises(MigrationError, match="invalid input value"):
            await db.migrator().downgrade(1)
        assert await labels(db) == ["admin", "member", "guest"]

        # dropping the table drops the type in the same revision
        async with db.engine().begin() as conn:
            await conn.execute(sa.text("DELETE FROM users"))
        dropped = await step(None, "drop users")
        assert "op.drop_enum('user_role'" in dropped.read_text()
        assert await labels(db) is None
        await db.migrator().downgrade(1)
        assert await labels(db) == ["guest", "admin"]
    finally:
        await db.dispose()


async def test_create_if_missing_and_parallel_lock(pg_config: Config) -> None:
    db = SynAlchemy(config=pg_config, metadata=build_models(1))
    try:
        for name in db.names:
            await db.migrator(name).make_revision("initial")
        # two concurrent runs on the same database: the advisory lock serialises them
        results = await asyncio.gather(db.migrator().upgrade(), db.migrator().upgrade())
        assert sorted(len(r.steps) for r in results) == [0, 1]
        await db.migrator("analytics").upgrade()
        assert (await db.migrator("analytics").status()).pending == 0
    finally:
        await db.dispose()


async def test_offline_sql_for_enum_add(pg_config: Config) -> None:
    db = SynAlchemy(config=pg_config, metadata=enum_models(["a", "b"]))
    try:
        await db.migrator().make_revision("initial")
    finally:
        await db.dispose()
    sql = db.migrator().sql()
    assert "CREATE TYPE user_role AS ENUM ('a', 'b')" in sql
    assert "CREATE TABLE users" in sql
