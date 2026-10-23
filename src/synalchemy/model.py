"""Declarative base support for ``__db_name__``."""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy.orm import DeclarativeBase

from synalchemy.config import DEFAULT_DB

#: Key in ``Table.info`` that holds the database name of a table.
DB_NAME_KEY = "db_name"


def db_name_of(table: Any) -> str:
    """Return the database a table belongs to (``"default"`` when unset)."""
    info = getattr(table, "info", None)
    if isinstance(info, dict):
        return info.get(DB_NAME_KEY, DEFAULT_DB)
    return DEFAULT_DB


class DBNameMixin:
    """Mixin for a declarative base that records ``__db_name__`` on each mapped table.

    Use it to build your own base::

        class Base(DBNameMixin, DeclarativeBase):
            pass

    Core tables can opt in with ``Table(..., info={"db_name": "analytics"})``.
    """

    __db_name__: ClassVar[str]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        table = cls.__dict__.get("__table__")
        name = getattr(cls, "__db_name__", None)
        if table is not None and name is not None:
            table.info[DB_NAME_KEY] = name


class Model(DBNameMixin, DeclarativeBase):
    """Ready-to-use declarative base. Set ``__db_name__`` to use a non-default database."""
