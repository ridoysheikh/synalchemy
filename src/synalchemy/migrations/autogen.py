"""Autogenerate: compare one database with its models and render revision code."""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from alembic.autogenerate import produce_migrations
from alembic.autogenerate.api import AutogenContext
from alembic.autogenerate.render import _indent, _render_cmd_body
from alembic.runtime.migration import MigrationContext

from synalchemy.config import Config
from synalchemy.migrations.enums import compare_enum_type, compare_enums, render_item

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from synalchemy.core import SynAlchemy

_STATEMENT_RE = re.compile(r"^(\s*)aop\.", re.M)


def table_filter(config: Config) -> Callable[[str], bool]:
    """``True`` for tables that migrations manage (not internal, not excluded)."""
    internal = {config.version_table}
    patterns = list(config.exclude_tables)

    def is_managed(name: str) -> bool:
        return name not in internal and not any(fnmatch.fnmatch(name, p) for p in patterns)

    return is_managed


def _render_item(type_: str, obj: Any, autogen_context: AutogenContext) -> str | bool:
    """Import the module of third-party column types (e.g. pgvector), then render as usual."""
    if type_ == "type":
        module = type(obj).__module__
        if module.split(".")[0] != "sqlalchemy":
            autogen_context.imports.add(f"import {module}")
    return render_item(type_, obj, autogen_context)


def render_diff(
    conn: Connection, db: SynAlchemy, name: str, use_async: bool = False
) -> tuple[str, str, str] | None:
    """Return ``(upgrade_code, downgrade_code, imports)``, or ``None`` when nothing changed."""
    metadata = db.metadata_for(name)
    is_managed = table_filter(db.config)

    def include_object(
        obj: Any, obj_name: str, type_: str, reflected: bool, compare_to: Any
    ) -> bool:
        return type_ != "table" or is_managed(obj_name)

    context = MigrationContext.configure(
        connection=conn,
        opts={
            "target_metadata": metadata,
            "include_object": include_object,
            "compare_type": compare_enum_type,
            "render_as_batch": conn.dialect.name == "sqlite" and not use_async,
            "render_item": _render_item,
            "alembic_module_prefix": "aop." if use_async else "op.",
            "sqlalchemy_module_prefix": "sa.",
            "user_module_prefix": None,
        },
    )
    upgrade_ops = produce_migrations(context, metadata).upgrade_ops
    assert upgrade_ops is not None
    before, after = compare_enums(conn, metadata, is_managed)
    upgrade_ops.ops[:0] = before
    upgrade_ops.ops.extend(after)
    if upgrade_ops.is_empty():
        return None

    render_context = AutogenContext(context, autogenerate=False)
    render_context.imports = set()
    upgrades = _indent(_render_cmd_body(upgrade_ops, render_context))
    downgrades = _indent(_render_cmd_body(upgrade_ops.reverse(), render_context))
    if use_async:
        upgrades = _STATEMENT_RE.sub(r"\1await aop.", upgrades)
        downgrades = _STATEMENT_RE.sub(r"\1await aop.", downgrades)
    return upgrades, downgrades, "\n".join(sorted(render_context.imports))
