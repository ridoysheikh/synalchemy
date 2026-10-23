"""ENUM support for autogenerate and migrations, on every dialect.

* **PostgreSQL** has standalone ENUM types. Alembic doesn't notice when their values
  change, so this module adds ``op.create_enum`` / ``op.drop_enum`` /
  ``op.sync_enum_values`` and :func:`compare_enums`, and renders ENUM columns with
  ``create_type=False`` so types are only created and dropped by those operations.
* **MySQL / MariaDB** keep ENUM values in the column type. :func:`compare_enum_type`
  makes autogenerate emit ``op.alter_column(..., type_=sa.Enum(...))`` whenever the
  values or their order change (Alembic < 1.16 doesn't compare them at all).
* **SQLite, SQL Server, Oracle and others** store a non-native ENUM as ``VARCHAR``.
  Normal type comparison handles a length change; nothing else is needed.

The PostgreSQL approach follows alembic-postgresql-enum (MIT); no code is copied from it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic.autogenerate.render import renderers
from alembic.operations import MigrateOperation, Operations


def _is_postgres(operations: Operations) -> bool:
    return operations.get_context().dialect.name == "postgresql"


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _type_name(operations: Operations, name: str, schema: str | None) -> str:
    preparer = operations.get_context().dialect.identifier_preparer
    quoted = preparer.quote(name)
    return f"{preparer.quote_schema(schema)}.{quoted}" if schema else quoted


def _schema_kwarg(schema: str | None) -> str:
    return f", schema={schema!r}" if schema else ""


# -- operations --------------------------------------------------------------


@Operations.register_operation("create_enum")
class CreateEnumOp(MigrateOperation):
    """``CREATE TYPE name AS ENUM (...)`` (PostgreSQL only)."""

    def __init__(self, name: str, values: Sequence[str], schema: str | None = None) -> None:
        self.name = name
        self.values = list(values)
        self.schema = schema

    @classmethod
    def create_enum(
        cls,
        operations: Operations,
        name: str,
        values: Sequence[str],
        *,
        schema: str | None = None,
    ) -> None:
        return operations.invoke(cls(name, values, schema))

    def reverse(self) -> DropEnumOp:
        return DropEnumOp(self.name, self.values, self.schema)


@Operations.register_operation("drop_enum")
class DropEnumOp(MigrateOperation):
    """``DROP TYPE name`` (PostgreSQL only). ``values`` is kept so it can be reversed."""

    def __init__(self, name: str, values: Sequence[str] = (), schema: str | None = None) -> None:
        self.name = name
        self.values = list(values)
        self.schema = schema

    @classmethod
    def drop_enum(
        cls,
        operations: Operations,
        name: str,
        values: Sequence[str] = (),
        *,
        schema: str | None = None,
    ) -> None:
        return operations.invoke(cls(name, values, schema))

    def reverse(self) -> CreateEnumOp:
        return CreateEnumOp(self.name, self.values, self.schema)


@Operations.register_operation("sync_enum_values")
class SyncEnumValuesOp(MigrateOperation):
    """Change the values of an existing ENUM type (PostgreSQL only).

    Pure additions use ``ALTER TYPE ... ADD VALUE``. Removing or reordering values
    recreates the type and converts every column that uses it. ``renames`` maps old
    values to new ones so existing rows are converted instead of failing.
    """

    def __init__(
        self,
        name: str,
        old_values: Sequence[str],
        new_values: Sequence[str],
        schema: str | None = None,
        renames: Mapping[str, str] | None = None,
    ) -> None:
        self.name = name
        self.old_values = list(old_values)
        self.new_values = list(new_values)
        self.schema = schema
        self.renames = dict(renames or {})

    @classmethod
    def sync_enum_values(
        cls,
        operations: Operations,
        name: str,
        old_values: Sequence[str],
        new_values: Sequence[str],
        *,
        schema: str | None = None,
        renames: Mapping[str, str] | None = None,
    ) -> None:
        return operations.invoke(cls(name, old_values, new_values, schema, renames))

    def reverse(self) -> SyncEnumValuesOp:
        inverted = {new: old for old, new in self.renames.items()}
        return SyncEnumValuesOp(self.name, self.new_values, self.old_values, self.schema, inverted)


@Operations.implementation_for(CreateEnumOp)
def _create_enum(operations: Operations, op: CreateEnumOp) -> None:
    if not _is_postgres(operations):
        return
    values = ", ".join(_literal(v) for v in op.values)
    operations.execute(
        f"CREATE TYPE {_type_name(operations, op.name, op.schema)} AS ENUM ({values})"
    )


@Operations.implementation_for(DropEnumOp)
def _drop_enum(operations: Operations, op: DropEnumOp) -> None:
    if not _is_postgres(operations):
        return
    operations.execute(f"DROP TYPE IF EXISTS {_type_name(operations, op.name, op.schema)}")


def _keeps_order(current: Sequence[str], new: Sequence[str]) -> bool:
    """True when ``new`` only adds values to ``current`` and keeps their order."""
    kept = set(current)
    return kept <= set(new) and [v for v in new if v in kept] == list(current)


@Operations.implementation_for(SyncEnumValuesOp)
def _sync_enum_values(operations: Operations, op: SyncEnumValuesOp) -> None:
    if not _is_postgres(operations):
        return
    type_name = _type_name(operations, op.name, op.schema)
    renames = {old: new for old, new in op.renames.items() if old in op.old_values}
    renamed = [renames.get(v, v) for v in op.old_values]
    in_place = not (set(renames.values()) & set(op.old_values)) and _keeps_order(
        renamed, op.new_values
    )
    if not in_place:
        _recreate_enum(operations, op, renames)
        return

    for old, new in renames.items():
        operations.execute(
            f"ALTER TYPE {type_name} RENAME VALUE {_literal(old)} TO {_literal(new)}"
        )
    present = set(renamed)
    for i, value in enumerate(op.new_values):
        if value in present:
            continue
        before = next((v for v in reversed(op.new_values[:i]) if v in present), None)
        after = next((v for v in op.new_values[i + 1 :] if v in present), None)
        if before is not None:
            position = f" AFTER {_literal(before)}"
        elif after is not None:
            position = f" BEFORE {_literal(after)}"
        else:
            position = ""
        operations.execute(
            f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS {_literal(value)}{position}"
        )
        present.add(value)


def _recreate_enum(operations: Operations, op: SyncEnumValuesOp, renames: dict[str, str]) -> None:
    context = operations.get_context()
    if context.as_sql:
        raise NotImplementedError(
            f"Removing or reordering values of ENUM {op.name!r} needs a live database "
            "connection; offline SQL output isn't supported for it."
        )
    preparer = context.dialect.identifier_preparer
    old_name = f"{op.name[:58]}__old"
    new_type = _type_name(operations, op.name, op.schema)
    old_type = _type_name(operations, old_name, op.schema)

    operations.execute(f"ALTER TYPE {new_type} RENAME TO {preparer.quote(old_name)}")
    values = ", ".join(_literal(v) for v in op.new_values)
    operations.execute(f"CREATE TYPE {new_type} AS ENUM ({values})")

    columns = operations.get_bind().execute(
        sa.text(
            "SELECT table_schema, table_name, column_name, data_type, column_default "
            "FROM information_schema.columns "
            "WHERE udt_schema = coalesce(:schema, current_schema()) "
            "AND udt_name IN (:scalar, :array)"
        ),
        {"schema": op.schema, "scalar": old_name, "array": f"_{old_name}"},
    )
    for table_schema, table_name, column_name, data_type, default in columns.all():
        table = f"{preparer.quote_schema(table_schema)}.{preparer.quote(table_name)}"
        column = preparer.quote(column_name)
        if data_type == "ARRAY":
            # subqueries aren't allowed in USING, so renames go through array_replace()
            expr = f"{column}::text[]"
            for o, n in renames.items():
                expr = f"array_replace({expr}, {_literal(o)}, {_literal(n)})"
            type_sql, using = f"{new_type}[]", f"{expr}::{new_type}[]"
        elif renames:
            cases = " ".join(f"WHEN {_literal(o)} THEN {_literal(n)}" for o, n in renames.items())
            type_sql = new_type
            using = f"(CASE {column}::text {cases} ELSE {column}::text END)::{new_type}"
        else:
            type_sql, using = new_type, f"{column}::text::{new_type}"
        if default is not None:
            operations.execute(f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT")
        operations.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {type_sql} USING {using}"
        )
        if default is not None:
            new_default = default.replace(old_name, op.name)
            for old, new in renames.items():
                new_default = new_default.replace(f"{_literal(old)}::", f"{_literal(new)}::")
            operations.execute(
                f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT {new_default}"
            )

    operations.execute(f"DROP TYPE {old_type}")


# -- rendering ---------------------------------------------------------------


def _prefix(autogen_context: Any) -> str:
    return autogen_context.opts.get("alembic_module_prefix", "op.")


@renderers.dispatch_for(CreateEnumOp)
def _render_create_enum(autogen_context: Any, op: CreateEnumOp) -> str:
    args = f"{op.name!r}, {op.values!r}{_schema_kwarg(op.schema)}"
    return f"{_prefix(autogen_context)}create_enum({args})"


@renderers.dispatch_for(DropEnumOp)
def _render_drop_enum(autogen_context: Any, op: DropEnumOp) -> str:
    return (
        f"{_prefix(autogen_context)}drop_enum({op.name!r}, {op.values!r}{_schema_kwarg(op.schema)})"
    )


@renderers.dispatch_for(SyncEnumValuesOp)
def _render_sync_enum_values(autogen_context: Any, op: SyncEnumValuesOp) -> list[str]:
    lines = []
    removed = [v for v in op.old_values if v not in op.new_values]
    if removed:
        lines.append(f"# ENUM {op.name!r} loses {removed!r}: rows still using them make this fail.")
        lines.append('# If a value was renamed, pass renames={"old": "new"} to convert those rows.')
    renames = f", renames={op.renames!r}" if op.renames else ""
    lines.append(
        f"{_prefix(autogen_context)}sync_enum_values({op.name!r}, {op.old_values!r}, "
        f"{op.new_values!r}{_schema_kwarg(op.schema)}{renames})"
    )
    return lines


def _enum_of(type_: Any) -> sa.Enum | None:
    if isinstance(type_, sa.TypeDecorator):
        type_ = getattr(type_, "impl_instance", type_.impl)
    if isinstance(type_, sa.ARRAY):
        type_ = type_.item_type
    if isinstance(type_, sa.Enum) and type_.native_enum and type_.name:
        return type_
    return None


def render_item(type_: str, obj: Any, autogen_context: Any) -> str | bool:
    """Render native ENUM columns as ``postgresql.ENUM(..., create_type=False)``."""
    if type_ != "type" or autogen_context.dialect.name != "postgresql":
        return False
    if not (isinstance(obj, sa.Enum) and obj.native_enum and obj.name):
        return False
    autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
    values = ", ".join(repr(v) for v in obj.enums)
    return (
        f"postgresql.ENUM({values}, name={obj.name!r}{_schema_kwarg(obj.schema)}, "
        "create_type=False)"
    )


# -- comparison --------------------------------------------------------------


def compare_enum_type(
    context: Any,
    inspected_column: Any,
    metadata_column: Any,
    inspected_type: Any,
    metadata_type: Any,
) -> bool | None:
    """``compare_type`` hook: ``True``/``False`` for ENUM pairs, ``None`` = Alembic default."""
    if not (isinstance(inspected_type, sa.Enum) and isinstance(metadata_type, sa.Enum)):
        return None
    if context.dialect.name == "postgresql":
        # values are synced on the type itself; only a switch to another type is a change
        return None if inspected_type.name != metadata_type.name else False
    return list(inspected_type.enums) != list(metadata_type.enums)


def compare_enums(
    conn: sa.Connection,
    metadata: sa.MetaData,
    is_managed_table: Callable[[str], bool] = lambda _name: True,
) -> tuple[list[MigrateOperation], list[MigrateOperation]]:
    """Diff ENUM types. Returns ops to run before and after Alembic's own ops."""
    if conn.dialect.name != "postgresql":
        return [], []

    default_schema = conn.execute(sa.text("SELECT current_schema()")).scalar_one()

    wanted: dict[tuple[str, str], list[str]] = {}
    for table in metadata.tables.values():
        for column in table.columns:
            enum = _enum_of(column.type)
            if enum is not None:
                wanted.setdefault((enum.schema or default_schema, enum.name), list(enum.enums))

    schemas = sorted({schema for schema, _ in wanted} | {default_schema})
    existing: dict[tuple[str, str], list[str]] = {}
    rows = conn.execute(
        sa.text(
            "SELECT n.nspname, t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname IN :schemas ORDER BY n.nspname, t.typname, e.enumsortorder"
        ).bindparams(sa.bindparam("schemas", expanding=True)),
        {"schemas": schemas},
    )
    for schema, name, label in rows:
        existing.setdefault((schema, name), []).append(label)

    usage: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
    rows = conn.execute(
        sa.text(
            "SELECT udt_schema, udt_name, data_type, table_schema, table_name, column_name "
            "FROM information_schema.columns WHERE udt_schema IN :schemas"
        ).bindparams(sa.bindparam("schemas", expanding=True)),
        {"schemas": schemas},
    )
    for udt_schema, udt_name, data_type, table_schema, table_name, column_name in rows:
        type_name = udt_name[1:] if data_type == "ARRAY" else udt_name
        usage.setdefault((udt_schema, type_name), []).append(
            (table_schema, table_name, column_name)
        )

    def schema_arg(schema: str) -> str | None:
        return None if schema == default_schema else schema

    def still_used(table_schema: str, table_name: str, column_name: str) -> bool:
        if not is_managed_table(table_name):
            return True
        key = table_name if table_schema == default_schema else f"{table_schema}.{table_name}"
        table = metadata.tables.get(key)
        return table is not None and column_name in table.c

    before: list[MigrateOperation] = []
    after: list[MigrateOperation] = []
    for (schema, name), values in wanted.items():
        current = existing.get((schema, name))
        if current is None:
            before.append(CreateEnumOp(name, values, schema_arg(schema)))
        elif current != values:
            before.append(SyncEnumValuesOp(name, current, values, schema_arg(schema)))
    for (schema, name), values in existing.items():
        if (schema, name) in wanted:
            continue
        if not any(still_used(*use) for use in usage.get((schema, name), [])):
            after.append(DropEnumOp(name, values, schema_arg(schema)))
    return before, after
