"""Configuration loading.

Sources, later ones overriding earlier ones:

1. ``[tool.synalchemy]`` in ``pyproject.toml`` or the top level of ``synalchemy.toml``
   (an explicit path can be given, or set ``SYNALCHEMY_CONFIG``)
2. environment variables (``SYNALCHEMY_DB_<NAME>_URL``, ``SYNALCHEMY_MODELS``, ...)
3. keyword overrides passed to :meth:`Config.load`

String values read from files support ``${VAR}`` and ``${VAR:-fallback}``.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.engine import make_url

from synalchemy.exceptions import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_DB = "default"

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ENV_DB_URL_RE = re.compile(r"^SYNALCHEMY_DB_(?P<name>[A-Z][A-Z0-9_]*)_URL$")
_INTERPOLATION_RE = re.compile(r"\$\{(?P<var>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}")

# Driver picked when a URL names only the backend, e.g. ``postgresql://``.
_ASYNC_DRIVERS = {
    "postgresql": "asyncpg",
    "sqlite": "aiosqlite",
    "mysql": "aiomysql",
    "mariadb": "aiomysql",
    "mssql": "aioodbc",
    "oracle": "oracledb",
}

_CONFIG_KEYS = {
    "databases",
    "models",
    "app",
    "metadata",
    "migrations_dir",
    "version_table",
    "exclude_tables",
    "engine_defaults",
}


def to_async_url(url: str) -> str:
    """Return ``url`` with an async driver filled in when none is given."""
    try:
        parsed = make_url(url)
    except Exception as exc:
        raise ConfigError(f"Invalid database URL {url!r}: {exc}") from exc
    backend, _, driver = parsed.drivername.partition("+")
    if backend == "postgres":
        backend = "postgresql"
    if not driver:
        driver = _ASYNC_DRIVERS.get(backend, "")
    drivername = f"{backend}+{driver}" if driver else backend
    return parsed.set(drivername=drivername).render_as_string(hide_password=False)


@dataclass(repr=False)
class DatabaseConfig:
    """Settings for one named database."""

    name: str
    url: str
    sync_url: str | None = None
    pool: str | None = None
    create_if_missing: bool = False
    engine_options: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ConfigError(
                f"Invalid database name {self.name!r}: use lowercase letters, digits and "
                "underscores, starting with a letter."
            )
        self.url = to_async_url(self.url)
        _check_pool(self.pool, self.name)

    def __repr__(self) -> str:
        safe_url = make_url(self.url).render_as_string(hide_password=True)
        return f"DatabaseConfig(name={self.name!r}, url={safe_url!r})"

    @property
    def backend(self) -> str:
        return make_url(self.url).get_backend_name()

    @classmethod
    def parse(cls, name: str, value: Any) -> DatabaseConfig:
        """Build from a URL string, a mapping, or an existing ``DatabaseConfig``."""
        if isinstance(value, DatabaseConfig):
            return value
        if isinstance(value, str):
            return cls(name=name, url=value)
        if isinstance(value, Mapping):
            options = dict(value)
            url = options.pop("url", None)
            if not url:
                raise ConfigError(f"Database {name!r} has no 'url'.")
            engine_options = dict(options.pop("engine_options", {}))
            known = {k: options.pop(k) for k in ("sync_url", "pool") if k in options}
            create = bool(options.pop("create_if_missing", False))
            engine_options.update(options)  # any other key goes to the engine
            return cls(
                name=name,
                url=url,
                create_if_missing=create,
                engine_options=engine_options,
                **known,
            )
        raise ConfigError(f"Database {name!r} must be a URL string or a table, got {value!r}.")


@dataclass
class Config:
    """Full SynAlchemy configuration."""

    databases: dict[str, DatabaseConfig]
    models: list[str] = field(default_factory=list)
    app: str | None = None
    metadata: str | None = None
    migrations_dir: Path = Path("migrations")
    version_table: str = "synalchemy_version"
    exclude_tables: list[str] = field(default_factory=list)
    engine_defaults: dict[str, Any] = field(default_factory=dict)
    root: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        self.databases = {
            name: DatabaseConfig.parse(name, value) for name, value in self.databases.items()
        }
        if DEFAULT_DB not in self.databases:
            raise ConfigError(
                f"A {DEFAULT_DB!r} database is required. Set it in the config file, "
                f"SYNALCHEMY_DB_DEFAULT_URL or DATABASE_URL."
            )
        defaults = dict(self.engine_defaults)
        default_pool = defaults.pop("pool", None)
        _check_pool(default_pool, "engine_defaults")
        for db in self.databases.values():
            db.engine_options = {**defaults, **db.engine_options}
            if db.pool is None:
                db.pool = default_pool
        self.migrations_dir = Path(self.migrations_dir)
        self.root = Path(self.root)

    @property
    def migrations_path(self) -> Path:
        if self.migrations_dir.is_absolute():
            return self.migrations_dir
        return self.root / self.migrations_dir

    @property
    def names(self) -> list[str]:
        return list(self.databases)

    def database(self, name: str) -> DatabaseConfig:
        try:
            return self.databases[name]
        except KeyError:
            known = ", ".join(sorted(self.databases))
            raise ConfigError(f"Unknown database {name!r}. Configured: {known}.") from None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, root: Path | None = None) -> Config:
        unknown = set(data) - _CONFIG_KEYS
        if unknown:
            raise ConfigError(f"Unknown config key(s): {', '.join(sorted(unknown))}.")
        values = dict(data)
        databases = values.pop("databases", None) or {}
        if not isinstance(databases, Mapping):
            raise ConfigError("'databases' must be a table of name = url / options.")
        models = values.pop("models", [])
        if isinstance(models, str):
            models = [models]
        return cls(
            databases=dict(databases),
            models=list(models),
            root=root or Path.cwd(),
            **values,
        )

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> Config:
        """Load config from file, environment and ``overrides``."""
        env = os.environ if env is None else env
        file_data, root = _read_file(path, env)
        data = _interpolate(file_data, env)
        data["databases"] = dict(data.get("databases") or {})

        for key, value in env.items():
            match = _ENV_DB_URL_RE.match(key)
            if match and value:
                name = match["name"].lower()
                current = data["databases"].get(name)
                if isinstance(current, Mapping):
                    data["databases"][name] = {**current, "url": value}
                else:
                    data["databases"][name] = value
        if DEFAULT_DB not in data["databases"] and env.get("DATABASE_URL"):
            data["databases"][DEFAULT_DB] = env["DATABASE_URL"]
        if env.get("SYNALCHEMY_MODELS"):
            data["models"] = [m.strip() for m in env["SYNALCHEMY_MODELS"].split(",") if m.strip()]
        if env.get("SYNALCHEMY_APP"):
            data["app"] = env["SYNALCHEMY_APP"]
        if env.get("SYNALCHEMY_MIGRATIONS_DIR"):
            data["migrations_dir"] = env["SYNALCHEMY_MIGRATIONS_DIR"]

        for key, value in overrides.items():
            if key == "databases":
                data["databases"].update(value)
            else:
                data[key] = value
        return cls.from_mapping(data, root=root)


def _check_pool(pool: str | None, where: str) -> None:
    from synalchemy.engines import POOL_KINDS

    if pool is not None and pool not in POOL_KINDS:
        raise ConfigError(f"{where}: pool must be one of {', '.join(POOL_KINDS)}; got {pool!r}.")


def find_config_file(env: Mapping[str, str] | None = None) -> Path | None:
    """Return the config file that :meth:`Config.load` would read, if any."""
    env = os.environ if env is None else env
    if env.get("SYNALCHEMY_CONFIG"):
        return Path(env["SYNALCHEMY_CONFIG"])
    cwd = Path.cwd()
    candidate = cwd / "synalchemy.toml"
    if candidate.is_file():
        return candidate
    candidate = cwd / "pyproject.toml"
    if candidate.is_file() and _section(candidate, explicit=False) is not None:
        return candidate
    return None


def _read_file(
    path: str | os.PathLike[str] | None, env: Mapping[str, str]
) -> tuple[dict[str, Any], Path]:
    if path is None:
        found = find_config_file(env)
        if found is None:
            return {}, Path.cwd()
        explicit = bool(env.get("SYNALCHEMY_CONFIG"))
    else:
        found, explicit = Path(path), True
    if not found.is_file():
        raise ConfigError(f"Config file not found: {found}")
    return dict(_section(found, explicit=explicit) or {}), found.resolve().parent


def _section(path: Path, *, explicit: bool) -> dict[str, Any] | None:
    try:
        raw = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Can't parse {path}: {exc}") from exc
    if path.name == "pyproject.toml":
        section = raw.get("tool", {}).get("synalchemy")
        if section is None and explicit:
            raise ConfigError(f"{path} has no [tool.synalchemy] table.")
        return section
    return raw.get("synalchemy", raw)


def _interpolate(value: Any, env: Mapping[str, str]) -> Any:
    if isinstance(value, str):

        def replace(match: re.Match[str]) -> str:
            var, default = match["var"], match["default"]
            if var in env:
                return env[var]
            if default is not None:
                return default
            raise ConfigError(f"Environment variable {var!r} is not set (used in config).")

        return _INTERPOLATION_RE.sub(replace, value)
    if isinstance(value, Mapping):
        return {key: _interpolate(item, env) for key, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, env) for item in value]
    return value
