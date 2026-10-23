from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import (
    AsyncAdaptedQueuePool,
    NullPool,
    QueuePool,
    SingletonThreadPool,
    StaticPool,
)

from synalchemy import Config, ConfigError, DatabaseConfig, SynAlchemy
from synalchemy.engines import engine_options, to_sync_url

from .conftest import build_models


def cfg(url: str, **kwargs) -> DatabaseConfig:
    return DatabaseConfig(name="x", url=url, **kwargs)


def test_pool_kinds_pick_the_right_class_and_drop_invalid_options() -> None:
    pg = "postgresql://u@h/d"
    tuned = {"pool_size": 5, "max_overflow": 2, "echo": True}

    opts = engine_options(cfg(pg, pool="null", engine_options=tuned), is_async=True)
    assert opts["poolclass"] is NullPool
    assert "pool_size" not in opts and "max_overflow" not in opts
    assert opts["echo"] is True and opts["pool_pre_ping"] is True

    assert (
        engine_options(cfg(pg, pool="queue"), is_async=True)["poolclass"] is AsyncAdaptedQueuePool
    )
    queue = engine_options(cfg(pg, pool="queue", engine_options=tuned), is_async=False)
    assert queue["poolclass"] is QueuePool and queue["pool_size"] == 5

    assert engine_options(cfg(pg, pool="static"), is_async=True)["poolclass"] is StaticPool
    single = engine_options(
        cfg("sqlite:///a.db", pool="single", engine_options=tuned), is_async=False
    )
    assert single["poolclass"] is SingletonThreadPool and single["pool_size"] == 5
    with pytest.raises(ConfigError, match="only for sync"):
        engine_options(cfg(pg, pool="single"), is_async=True)
    with pytest.raises(ConfigError, match="pool must be one of"):
        cfg(pg, pool="huge")


def test_dialect_defaults() -> None:
    assert "poolclass" not in engine_options(cfg("postgresql://u@h/d"), is_async=True)
    mysql = engine_options(cfg("mysql://u@h/d"), is_async=True)
    assert mysql["pool_recycle"] == 3600 and mysql["pool_pre_ping"] is True
    assert "pool_pre_ping" not in engine_options(cfg("sqlite:///a.db"), is_async=True)
    memory = engine_options(cfg("sqlite://"), is_async=True)
    assert memory["poolclass"] is StaticPool
    # explicit options win over defaults
    assert (
        engine_options(cfg("mysql://u@h/d", engine_options={"pool_recycle": 60}), is_async=True)[
            "pool_recycle"
        ]
        == 60
    )


def test_engine_defaults_apply_to_every_database() -> None:
    config = Config(
        databases={"default": {"url": "postgresql://u@h/a", "pool_size": 3}, "b": "sqlite:///b.db"},
        engine_defaults={"pool": "queue", "pool_size": 10, "echo": True},
    )
    default, other = config.database("default"), config.database("b")
    assert default.engine_options == {"pool_size": 3, "echo": True}
    assert other.engine_options == {"pool_size": 10, "echo": True}
    assert default.pool == other.pool == "queue"
    explicit = Config(
        databases={"default": {"url": "sqlite:///a.db", "pool": "null"}},
        engine_defaults={"pool": "queue"},
    )
    assert explicit.database("default").pool == "null"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("sqlite+aiosqlite:///x.db", "sqlite+pysqlite:///x.db"),
        ("mysql+aiomysql://u@h/d", "mysql+pymysql://u@h/d"),
        ("mysql+asyncmy://u@h/d", "mysql+pymysql://u@h/d"),
        ("mssql+aioodbc://u@h/d", "mssql+pyodbc://u@h/d"),
        ("oracle+oracledb://u@h/d", "oracle+oracledb://u@h/d"),
        ("postgresql+psycopg://u@h/d", "postgresql+psycopg://u@h/d"),
        ("postgresql+asyncpg://u@h/d", "postgresql+psycopg://u@h/d"),
    ],
)
def test_sync_url(url: str, expected: str) -> None:
    assert to_sync_url(url) == expected


async def test_sync_and_async_sessions_share_routing(make_db) -> None:
    db = make_db(build_models(1))
    await db.create_all()
    try:
        users, events = db.metadata.tables["users"], db.metadata.tables["events"]
        with db.sync_session() as session:
            session.execute(sa.insert(users).values(id=1, name="ada"))
            session.execute(sa.insert(events).values(id=1, kind="signup"))
            session.commit()
            assert session.execute(sa.select(sa.func.count()).select_from(events)).scalar() == 1

        async with db.session() as session:
            assert (await session.execute(sa.select(users.c.name))).scalar() == "ada"
            assert (await session.execute(sa.select(events.c.kind))).scalar() == "signup"

        status = db.pool_status()
        assert set(status) == {"default", "analytics", "default (sync)", "analytics (sync)"}
        assert isinstance(db.migration_engine("default").pool, NullPool)
    finally:
        await db.dispose()
    assert db.pool_status() == {}


def test_memory_sqlite_is_shared_across_connections() -> None:
    db = SynAlchemy({"default": "sqlite://"}, metadata=sa.MetaData())
    engine = db.sync_engine()
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE t (x INTEGER)"))
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM t")).scalar() == 0
    assert db.migration_engine() is db.engine()
    db.dispose_sync()


def test_explicit_sync_url_is_used() -> None:
    db = SynAlchemy(
        {"default": {"url": "postgresql://u@h/d", "sync_url": "sqlite:///./other.db"}},
        metadata=sa.MetaData(),
    )
    assert db.sync_engine().url.get_backend_name() == "sqlite"
    db.dispose_sync()
