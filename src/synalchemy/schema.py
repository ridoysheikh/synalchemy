"""Schema export: one JSON file per database for services that share it.

Other services (Go, JavaScript, Python without SynAlchemy, ...) read the database but
never migrate it. Each JSON file describes one database's tables as the models define
them, stamped with the head revision. A service can check that stamp against the
database's version table to catch a schema mismatch. Turning the JSON into code for a
given language is up to the service.

The output is deterministic: the same models and revision give the same bytes, so the
files diff cleanly in git.
"""

from __future__ import annotations

import enum
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa
from sqlalchemy.dialects import registry
from sqlalchemy.engine import Dialect, make_url
from sqlalchemy.exc import CompileError, UnsupportedCompilationError

if TYPE_CHECKING:
    from synalchemy.core import SynAlchemy

FORMAT = "synalchemy.schema/1"

# Checked in order: the first matching class names the column's kind.
_KINDS: list[tuple[type[sa.types.TypeEngine[Any]], str]] = [
    (sa.Enum, "enum"),
    (sa.Boolean, "boolean"),
    (sa.SmallInteger, "smallint"),
    (sa.BigInteger, "bigint"),
    (sa.Integer, "integer"),
    (sa.Float, "float"),
    (sa.Numeric, "decimal"),
    (sa.Uuid, "uuid"),
    (sa.String, "string"),
    (sa.DateTime, "datetime"),
    (sa.Date, "date"),
    (sa.Time, "time"),
    (sa.Interval, "interval"),
    (sa.LargeBinary, "binary"),
    (sa.JSON, "json"),
    (sa.ARRAY, "array"),
]


def build(db: SynAlchemy, name: str) -> dict[str, Any]:
    """The schema of database ``name``, from its models, as a JSON-ready dict."""
    dialect = _dialect(db, name)
    metadata = db.metadata_for(name)
    is_managed = _table_filter(db)
    tables = [
        _table(table, dialect)
        for table in sorted(metadata.tables.values(), key=lambda t: (t.schema or "", t.name))
        if is_managed(table.name)
    ]
    enums: dict[tuple[str | None, str], dict[str, Any]] = {}
    for table in tables:
        for column in table["columns"]:
            if column.get("enum", {}).get("name"):
                info = column["enum"]
                enums.setdefault((info["schema"], info["name"]), info)
    body = {"enums": list(enums.values()), "tables": tables}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {
        "format": FORMAT,
        "database": name,
        "dialect": dialect.name,
        "revision": db.migrator(name).chain.head,
        "version_table": db.config.version_table,
        "fingerprint": "sha256:" + hashlib.sha256(canonical.encode()).hexdigest(),
        **body,
    }


def export(
    db: SynAlchemy, names: Iterable[str] | None = None, directory: Path | None = None
) -> list[Path]:
    """Write ``<directory>/<name>.json`` for each database. Returns the files written.

    ``directory`` defaults to ``[schema] dir`` from the config.
    """
    directory = directory or db.config.schema.path
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names or db.names:
        path = directory / f"{name}.json"
        text = json.dumps(build(db, name), indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths


# -- pieces ------------------------------------------------------------------


def _dialect(db: SynAlchemy, name: str) -> Dialect:
    backend = make_url(db.config.database(name).url).get_backend_name()
    return registry.load(backend)()


def _table_filter(db: SynAlchemy) -> Any:
    from synalchemy.migrations.autogen import table_filter

    return table_filter(db.config)


def _table(table: sa.Table, dialect: Dialect) -> dict[str, Any]:
    name_of = _namer(dialect)
    pk = table.primary_key
    out: dict[str, Any] = {
        "name": table.name,
        "schema": table.schema,
        "comment": table.comment,
        "columns": [_column(column, table, dialect) for column in table.columns],
        "primary_key": [c.name for c in pk.columns],
        "foreign_keys": [],
        "unique": [],
        "indexes": [],
        "checks": [],
    }
    constraints = sorted(table.constraints, key=lambda c: (type(c).__name__, name_of(c) or ""))
    for constraint in constraints:
        if isinstance(constraint, sa.ForeignKeyConstraint):
            target = constraint.elements[0].column.table
            out["foreign_keys"].append(
                {
                    "name": name_of(constraint),
                    "columns": [c.name for c in constraint.columns],
                    "references": {
                        "table": target.name,
                        "schema": target.schema,
                        "columns": [e.column.name for e in constraint.elements],
                    },
                    "on_delete": constraint.ondelete,
                    "on_update": constraint.onupdate,
                }
            )
        elif isinstance(constraint, sa.UniqueConstraint):
            out["unique"].append(
                {"name": name_of(constraint), "columns": [c.name for c in constraint.columns]}
            )
        elif isinstance(constraint, sa.CheckConstraint):
            out["checks"].append(
                {"name": name_of(constraint), "sql": _sql(constraint.sqltext, dialect)}
            )
    for index in sorted(table.indexes, key=lambda i: name_of(i) or ""):
        out["indexes"].append(
            {
                "name": name_of(index),
                "columns": [
                    c.name if isinstance(c, sa.Column) else _sql(c, dialect)
                    for c in index.expressions
                ],
                "unique": bool(index.unique),
            }
        )
    return out


def _column(column: sa.Column[Any], table: sa.Table, dialect: Dialect) -> dict[str, Any]:
    type_ = column.type
    base = type_.impl_instance if isinstance(type_, sa.TypeDecorator) else type_
    out: dict[str, Any] = {
        "name": column.name,
        "type": _compile_type(type_, dialect),
        "kind": _kind(base),
        "nullable": bool(column.nullable),
        "primary_key": bool(column.primary_key),
        "autoincrement": column is table.autoincrement_column,
    }
    out.update(_type_details(base, dialect))
    out["server_default"] = _server_default(column, dialect)
    out["client_default"] = _client_default(column)
    out["computed"] = _sql(column.computed.sqltext, dialect) if column.computed else None
    out["comment"] = column.comment
    return out


def _kind(type_: sa.types.TypeEngine[Any]) -> str:
    for cls, kind in _KINDS:
        if isinstance(type_, cls):
            return kind
    return "other"


def _type_details(type_: sa.types.TypeEngine[Any], dialect: Dialect) -> dict[str, Any]:
    if isinstance(type_, sa.Enum):
        return {
            "enum": {
                "name": type_.name,
                "schema": type_.schema,
                "values": list(type_.enums),
                "native": bool(type_.native_enum),
            }
        }
    if isinstance(type_, sa.String):
        return {"length": type_.length}
    if isinstance(type_, sa.Numeric) and not isinstance(type_, sa.Float):
        return {"precision": type_.precision, "scale": type_.scale}
    if isinstance(type_, (sa.DateTime, sa.Time)):
        return {"timezone": bool(type_.timezone)}
    if isinstance(type_, sa.ARRAY):
        item = type_.item_type
        return {"item": {"type": _compile_type(item, dialect), "kind": _kind(item)}}
    return {}


def _compile_type(type_: sa.types.TypeEngine[Any], dialect: Dialect) -> str:
    try:
        return type_.compile(dialect=dialect)
    except (CompileError, UnsupportedCompilationError):
        return type(type_).__name__.upper()


def _server_default(column: sa.Column[Any], dialect: Dialect) -> str | None:
    default = column.server_default
    if not isinstance(default, sa.DefaultClause):
        return None
    if isinstance(default.arg, str):
        return default.arg
    return _sql(default.arg, dialect)


def _client_default(column: sa.Column[Any]) -> Any:
    """A Python-side default: the database won't fill it, so other writers must."""
    default = column.default
    if default is None:
        return None
    if isinstance(default, sa.Sequence):
        return {"sequence": default.name}
    arg = getattr(default, "arg", None)
    if callable(arg):
        fn = getattr(arg, "__wrapped__", arg)
        return {"callable": getattr(fn, "__qualname__", repr(fn))}
    if isinstance(arg, sa.ClauseElement):
        return {"sql": str(arg)}
    if isinstance(arg, enum.Enum):
        arg = arg.value
    if arg is None or isinstance(arg, (bool, int, float, str)):
        return {"value": arg}
    return {"value": str(arg)}


def _sql(element: Any, dialect: Dialect) -> str:
    try:
        return str(element.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))
    except (CompileError, UnsupportedCompilationError):
        return str(element)


def _namer(dialect: Dialect) -> Any:
    """Constraint and index names as created, with the naming convention applied."""
    preparer = dialect.identifier_preparer

    def name_of(item: sa.Constraint | sa.Index) -> str | None:
        if item.name is None:
            return None
        try:
            return preparer.format_constraint(item, _alembic_quote=False)
        except Exception:
            return str(item.name)

    return name_of
