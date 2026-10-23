from __future__ import annotations

from pathlib import Path

import pytest

from synalchemy import Config, ConfigError, DatabaseConfig
from synalchemy.config import to_async_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("postgres://u:p@h/db", "postgresql+asyncpg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite+aiosqlite:///x.db"),
        ("mysql://u@h/db", "mysql+aiomysql://u@h/db"),
        ("postgresql+psycopg://u@h/db", "postgresql+psycopg://u@h/db"),
    ],
)
def test_async_driver_is_filled_in(url: str, expected: str) -> None:
    assert to_async_url(url) == expected


def test_load_toml_with_interpolation_and_env(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "synalchemy.toml").write_text(
        """
models = ["app.models"]
[databases.default]
url = "${MAIN_URL}"
pool_size = 5
[databases.analytics]
url = "${AN_URL:-sqlite:///an.db}"
create_if_missing = true
"""
    )
    monkeypatch.chdir(tmp_path)
    env = {"MAIN_URL": "postgresql://u:p@h/main", "SYNALCHEMY_DB_REPORTS_URL": "sqlite:///r.db"}
    config = Config.load(env=env)
    assert config.names == ["default", "analytics", "reports"]
    assert config.database("default").url == "postgresql+asyncpg://u:p@h/main"
    assert config.database("default").engine_options == {"pool_size": 5}
    assert config.database("analytics").create_if_missing
    assert config.database("analytics").url == "sqlite+aiosqlite:///an.db"
    assert config.models == ["app.models"]
    assert config.root == tmp_path.resolve()


def test_env_url_overrides_file_but_keeps_options(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.synalchemy.databases.default]
url = "sqlite:///file.db"
echo = true
"""
    )
    monkeypatch.chdir(tmp_path)
    config = Config.load(env={"SYNALCHEMY_DB_DEFAULT_URL": "sqlite:///env.db"})
    assert config.database("default").url.endswith("env.db")
    assert config.database("default").engine_options == {"echo": True}


def test_database_url_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    config = Config.load(env={"DATABASE_URL": "sqlite:///d.db"})
    assert config.names == ["default"]


def test_missing_default_and_unknown_keys(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="'default' database is required"):
        Config.load(env={})
    with pytest.raises(ConfigError, match="Unknown config key"):
        Config.from_mapping({"databases": {"default": "sqlite://"}, "nope": 1})
    (tmp_path / "synalchemy.toml").write_text('[databases]\ndefault = "${MISSING}"\n')
    with pytest.raises(ConfigError, match="not set"):
        Config.load(env={})


def test_bad_names_and_secret_repr() -> None:
    with pytest.raises(ConfigError, match="Invalid database name"):
        DatabaseConfig(name="Bad-Name", url="sqlite://")
    assert "secret" not in repr(DatabaseConfig(name="x", url="postgresql://u:secret@h/db"))


def test_unknown_database_lookup() -> None:
    config = Config(databases={"default": "sqlite://"})
    with pytest.raises(ConfigError, match="Unknown database 'other'"):
        config.database("other")
