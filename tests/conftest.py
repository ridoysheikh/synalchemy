from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from synalchemy import Config, DBNameMixin, SynAlchemy

PG_URL = os.environ.get("SYNALCHEMY_TEST_PG_URL")


def build_models(version: int = 1) -> sa.MetaData:
    """Fresh metadata with ``users`` (default) and ``events`` (analytics).

    version 2 adds ``users.email`` and an ``analytics.sessions`` table.
    """

    class Base(DBNameMixin, DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str] = mapped_column(sa.String(50))
        if version >= 2:
            email: Mapped[str | None] = mapped_column(sa.String(120))

    class Event(Base):
        __tablename__ = "events"
        __db_name__ = "analytics"
        id: Mapped[int] = mapped_column(primary_key=True)
        kind: Mapped[str] = mapped_column(sa.String(30))

    if version >= 2:

        class Session(Base):
            __tablename__ = "sessions"
            __db_name__ = "analytics"
            id: Mapped[int] = mapped_column(primary_key=True)

    return Base.metadata


@pytest.fixture
def sqlite_config(tmp_path: Path) -> Config:
    return Config(
        databases={
            "default": f"sqlite:///{tmp_path / 'main.db'}",
            "analytics": f"sqlite:///{tmp_path / 'analytics.db'}",
        },
        root=tmp_path,
    )


@pytest.fixture
def make_db(sqlite_config: Config) -> Callable[..., SynAlchemy]:
    created: list[SynAlchemy] = []

    def factory(metadata: sa.MetaData, config: Config | None = None) -> SynAlchemy:
        db = SynAlchemy(config=config or sqlite_config, metadata=metadata)
        created.append(db)
        return db

    yield factory
    # engines are disposed by the async tests themselves; nothing pooled leaks for sqlite


@pytest.fixture
async def pg_config(tmp_path: Path) -> AsyncIterator[Config]:
    if not PG_URL:
        pytest.skip("set SYNALCHEMY_TEST_PG_URL to run PostgreSQL tests")
    base = make_url(PG_URL)
    suffix = uuid.uuid4().hex[:8]
    names = {"default": f"syn_main_{suffix}", "analytics": f"syn_an_{suffix}"}
    config = Config(
        databases={
            key: {
                "url": base.set(database=dbname).render_as_string(hide_password=False),
                "create_if_missing": True,
            }
            for key, dbname in names.items()
        },
        root=tmp_path,
    )
    yield config
    from sqlalchemy.ext.asyncio import create_async_engine

    from synalchemy.config import to_async_url

    admin = create_async_engine(
        to_async_url(base.set(database="postgres").render_as_string(hide_password=False)),
        isolation_level="AUTOCOMMIT",
    )
    async with admin.connect() as conn:
        for dbname in names.values():
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
    await admin.dispose()
