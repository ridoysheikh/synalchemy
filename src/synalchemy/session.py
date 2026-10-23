"""A session that sends each statement to the database its tables belong to."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sqlalchemy import Table, inspect
from sqlalchemy.orm import Mapper, Session
from sqlalchemy.sql.util import find_tables

from synalchemy.config import DEFAULT_DB
from synalchemy.exceptions import RoutingError
from synalchemy.model import DB_NAME_KEY, db_name_of

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


class RoutingSession(Session):
    """Session that picks an engine per statement. Used directly or under ``AsyncSession``.

    The database is chosen from, in order: ``bind_arguments={"db_name": ...}``,
    the mapper's table, then the tables referenced by the statement.
    """

    _engine_for: Callable[[str], Engine]

    def get_bind(self, mapper: Any = None, clause: Any = None, **kw: Any) -> Engine:
        return self._engine_for(kw.get("db_name") or self._route(mapper, clause))

    @staticmethod
    def _route(mapper: Any, clause: Any) -> str:
        names: set[str] = set()
        if mapper is not None:
            if not isinstance(mapper, Mapper):
                mapper = inspect(mapper)
            table = mapper.local_table
            if isinstance(getattr(table, "info", None), dict) and DB_NAME_KEY in table.info:
                names.add(table.info[DB_NAME_KEY])
            else:
                names.add(getattr(mapper.class_, "__db_name__", DEFAULT_DB))
        if clause is not None:
            names.update(
                db_name_of(table)
                for table in find_tables(clause, include_crud=True, include_aliases=True)
                if isinstance(table, Table)
            )
        if len(names) > 1:
            raise RoutingError(
                f"Statement mixes tables from several databases ({', '.join(sorted(names))}). "
                "Cross-database queries aren't supported; split it into one query per database."
            )
        return names.pop() if names else DEFAULT_DB
