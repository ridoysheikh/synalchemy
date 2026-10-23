"""Exception types raised by SynAlchemy."""

from __future__ import annotations


class SynAlchemyError(Exception):
    """Base class for every SynAlchemy error."""


class ConfigError(SynAlchemyError):
    """The configuration is missing, malformed, or refers to an unknown database."""


class RoutingError(SynAlchemyError):
    """A statement can't be routed to exactly one database."""


class ChainError(SynAlchemyError):
    """The revision files of a database don't form a single linear chain."""


class MigrationError(SynAlchemyError):
    """Applying, reverting, or generating a migration failed."""
