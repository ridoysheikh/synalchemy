"""Settings for real deployments: ``.env`` files, env-driven pools, poolers, serverless."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from synalchemy import Config, ConfigError, DatabaseConfig, SynAlchemy, db
from synalchemy.engines import SERVERLESS_ENV, engine_options

TOML = """
env_file = ".env"
[databases.default]
url = "${DB_URL}"
migration_url = "${DB_DIRECT_URL:-}"
pool = "${DB_POOL:-queue}"
pool_size = "${DB_POOL_SIZE:-5}"
pool_recycle = "${DB_POOL_RECYCLE:-1800}"
echo = "${DB_ECHO:-false}"
"""


@pytest.fixture(autouse=True)
def no_serverless(monkeypatch) -> None:
    for name in SERVERLESS_ENV:
        monkeypatch.delenv(name, raising=False)


def write(tmp_path: Path, env: str) -> None:
    (tmp_path / "synalchemy.toml").write_text(TOML)
    (tmp_path / ".env").write_text(env)


def test_env_file_fills_values_and_real_environment_wins(tmp_path: Path, monkeypatch) -> None:
    write(
        tmp_path,
        '# local\nexport DB_URL="postgresql://u:p@h/app"\nDB_POOL=\nDB_POOL_SIZE=7  # tuned\n',
    )
    monkeypatch.chdir(tmp_path)
    main = Config.load(env={}).database("default")
    assert main.url == "postgresql+asyncpg://u:p@h/app"
    assert main.pool == "queue"  # empty in .env -> the fallback, as in the shell
    assert main.migration_url is None  # ${VAR:-} with nothing set means "not set"
    assert main.engine_options == {"pool_size": 7, "pool_recycle": 1800, "echo": False}

    main = Config.load(env={"DB_POOL_SIZE": "9", "DB_ECHO": "yes"}).database("default")
    assert main.engine_options["pool_size"] == 9 and main.engine_options["echo"] is True


def test_missing_env_file_is_fine_but_bad_numbers_are_not(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "synalchemy.toml").write_text(TOML)
    monkeypatch.chdir(tmp_path)
    assert Config.load(env={"DB_URL": "sqlite:///a.db"}).database("default").pool == "queue"
    with pytest.raises(ConfigError, match="pool_size must be a whole number"):
        Config.load(env={"DB_URL": "sqlite:///a.db", "DB_POOL_SIZE": "lots"})


def test_config_is_found_from_a_subfolder(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path, "DB_URL=sqlite:///app.db\n")
    (tmp_path / "tests" / "unit").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "tests" / "unit")
    config = Config.load(env={})
    assert config.root == tmp_path.resolve()
    assert config.migrations_path == tmp_path.resolve() / "migrations"


def test_external_pool_turns_off_prepared_statements() -> None:
    pg = DatabaseConfig(
        name="x",
        url="postgresql://u@pooler/d",
        pool="external",
        engine_options={"pool_size": 5, "connect_args": {"ssl": "require"}},
    )
    opts = engine_options(pg, is_async=True)
    assert opts["poolclass"] is NullPool and "pool_size" not in opts
    assert opts["connect_args"] == {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
        "ssl": "require",
    }
    psycopg = DatabaseConfig(name="x", url="postgresql+psycopg://u@pooler/d", pool="external")
    assert engine_options(psycopg, is_async=True)["connect_args"] == {"prepare_threshold": None}
    mysql = DatabaseConfig(name="x", url="mysql://u@proxysql/d", pool="external")
    assert "connect_args" not in engine_options(mysql, is_async=True)


def test_migrations_use_the_direct_url() -> None:
    syn = SynAlchemy(
        {
            "default": {
                "url": "postgresql://u@pooler/d",
                "migration_url": "postgresql://u@direct/d",
                "pool": "external",
                "connect_args": {"ssl": "require"},
            },
            "other": {"url": "postgresql://u@pooler/o", "pool": "external"},
        }
    )
    direct = syn.migration_engine()
    assert direct.url.host == "direct" and direct.url.drivername == "postgresql+asyncpg"
    assert isinstance(direct.pool, NullPool)
    assert direct.dialect.create_connect_args(direct.url)[1].get("statement_cache_size") is None
    pooled = syn.migration_engine("other")  # no direct URL: keeps the pooler's settings
    assert pooled.url.host == "pooler" and isinstance(pooled.pool, NullPool)


def test_auto_pool_is_unpooled_on_serverless(monkeypatch) -> None:
    pg = DatabaseConfig(name="x", url="postgresql://u@h/d", engine_options={"pool_size": 5})
    assert "poolclass" not in engine_options(pg, is_async=True)
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "checkout")
    opts = engine_options(pg, is_async=True)
    assert opts["poolclass"] is NullPool and "pool_size" not in opts
    queue = DatabaseConfig(name="x", url="postgresql://u@h/d", pool="queue")
    assert engine_options(queue, is_async=True)["poolclass"] is AsyncAdaptedQueuePool


async def test_default_instance_builds_from_the_config_file(tmp_path: Path, monkeypatch) -> None:
    write(tmp_path, f"DB_URL=sqlite:///{tmp_path / 'app.db'}\n")
    monkeypatch.chdir(tmp_path)
    metadata = sa.MetaData()
    users = sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    db.reset()
    try:
        assert repr(db) == "<synalchemy.db: not built yet>"
        db.use(SynAlchemy.from_config(metadata=metadata))
        await db.create_all("default")
        async with db.session() as session:
            await session.execute(sa.insert(users).values(id=1))
            await session.commit()
            assert (await session.scalars(sa.select(users.c.id))).all() == [1]
        await db.dispose()
        db.reset()
        assert db.instance.config.root == tmp_path.resolve()  # built on first use
    finally:
        db.reset()


def test_relative_sqlite_files_are_relative_to_the_config_file(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "synalchemy.toml").write_text(
        '[databases]\ndefault = "sqlite:///./data/app.db"\nmemory = "sqlite://"\n'
    )
    (tmp_path / "sub").mkdir()
    monkeypatch.chdir(tmp_path / "sub")
    config = Config.load(env={})
    assert config.database("default").url == f"sqlite+aiosqlite:///{tmp_path.resolve()}/data/app.db"
    assert config.database("memory").url == "sqlite+aiosqlite://"


async def test_lifespan_yields_no_state(tmp_path: Path) -> None:
    syn = SynAlchemy({"default": f"sqlite:///{tmp_path / 'a.db'}"})
    async with syn.lifespan(object()) as state:  # Starlette merges a yielded value into app state
        assert state is None
