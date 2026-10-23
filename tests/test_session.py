from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from synalchemy import ConfigError, DBNameMixin, RoutingError


async def test_models_are_routed_to_their_database(make_db) -> None:
    class Base(DBNameMixin, DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]

    class Event(Base):
        __tablename__ = "events"
        __db_name__ = "analytics"
        id: Mapped[int] = mapped_column(primary_key=True)
        kind: Mapped[str]

    db = make_db(Base.metadata)
    await db.create_all()
    try:
        async with db.session() as session:
            session.add_all([User(name="ada"), Event(kind="signup")])
            await session.commit()

            assert (await session.scalars(sa.select(User.name))).all() == ["ada"]
            assert (await session.scalars(sa.select(Event.kind))).all() == ["signup"]

            with pytest.raises(RoutingError, match="several databases"):
                await session.execute(sa.select(User.id, Event.id))

            raw = await session.execute(
                sa.text("SELECT count(*) FROM events"), bind_arguments={"db_name": "analytics"}
            )
            assert raw.scalar() == 1

        # the rows really live in separate files
        async with db.engine("default").connect() as conn:
            tables = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
            assert tables == ["users"]
        async with db.engine("analytics").connect() as conn:
            tables = await conn.run_sync(lambda c: sa.inspect(c).get_table_names())
            assert tables == ["events"]
    finally:
        await db.dispose()


async def test_core_tables_route_by_info(make_db) -> None:
    metadata = sa.MetaData()
    logs = sa.Table(
        "logs",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        info={"db_name": "analytics"},
    )
    db = make_db(metadata)
    await db.create_all()
    try:
        async with db.session() as session:
            await session.execute(sa.insert(logs).values(id=1))
            await session.commit()
            assert (await session.execute(sa.select(logs.c.id))).scalar() == 1
    finally:
        await db.dispose()


def test_unknown_database_and_cross_db_foreign_keys(make_db) -> None:
    class Base(DBNameMixin, DeclarativeBase):
        pass

    class Orphan(Base):
        __tablename__ = "orphans"
        __db_name__ = "missing"
        id: Mapped[int] = mapped_column(primary_key=True)

    with pytest.raises(ConfigError, match="isn't configured"):
        make_db(Base.metadata).metadata_for("default")

    class Base2(DBNameMixin, DeclarativeBase):
        pass

    class Parent(Base2):
        __tablename__ = "parents"
        id: Mapped[int] = mapped_column(primary_key=True)

    class Child(Base2):
        __tablename__ = "children"
        __db_name__ = "analytics"
        id: Mapped[int] = mapped_column(primary_key=True)
        parent_id: Mapped[int] = mapped_column(sa.ForeignKey("parents.id"))

    with pytest.raises(ConfigError, match="can't cross databases"):
        make_db(Base2.metadata).metadata_for("analytics")


def test_engines_are_lazy(make_db) -> None:
    db = make_db(sa.MetaData())
    assert db._engines == {}
    engine = db.engine("analytics")
    assert db.engine("analytics") is engine
    assert list(db._engines) == ["analytics"]
