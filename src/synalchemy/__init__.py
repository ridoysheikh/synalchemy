"""SynAlchemy: async multi-database toolkit for SQLAlchemy 2.x."""

from synalchemy.config import DEFAULT_DB, Config, DatabaseConfig
from synalchemy.core import SynAlchemy
from synalchemy.default import DefaultSynAlchemy, db
from synalchemy.exceptions import (
    ChainError,
    ConfigError,
    MigrationError,
    RoutingError,
    SynAlchemyError,
)
from synalchemy.model import DB_NAME_KEY, DBNameMixin, Model, db_name_of

__version__ = "0.3.2"

__all__ = [
    "DB_NAME_KEY",
    "DEFAULT_DB",
    "ChainError",
    "Config",
    "ConfigError",
    "DBNameMixin",
    "DatabaseConfig",
    "DefaultSynAlchemy",
    "MigrationError",
    "Model",
    "RoutingError",
    "SynAlchemy",
    "SynAlchemyError",
    "__version__",
    "db",
    "db_name_of",
]
