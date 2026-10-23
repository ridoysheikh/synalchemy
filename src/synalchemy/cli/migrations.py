"""``migrations``: create and inspect revision files. Never changes a schema."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from synalchemy.cli._common import (
    ConfigOption,
    DbOption,
    handle_errors,
    load_app,
    run,
    select_databases,
    short,
)
from synalchemy.config import Config, find_config_file
from synalchemy.exceptions import ChainError, ConfigError

migrations_app = typer.Typer(
    name="migrations",
    help="Create and inspect migration files. Never changes a database schema.",
    no_args_is_help=True,
    add_completion=False,
)

_CONFIG_STUB = """\
# SynAlchemy configuration. Strings support ${ENV_VAR} and ${ENV_VAR:-fallback}.
models = ["app.models"]          # modules to import so every model is registered
migrations_dir = "migrations"

# [engine_defaults]              # applied to every database
# pool = "queue"                 # auto | queue | null | static | single
# pool_size = 10

[databases.default]
url = "${DATABASE_URL:-sqlite+aiosqlite:///./app.db}"

# [databases.analytics]          # models with __db_name__ = "analytics" go here
# url = "${ANALYTICS_DATABASE_URL}"
# create_if_missing = true
"""


@migrations_app.command()
@handle_errors
def init(config: ConfigOption = None) -> None:
    """Create a config file (if none exists) and one migrations folder per database."""
    if config is None and find_config_file() is None:
        stub = Path.cwd() / "synalchemy.toml"
        stub.write_text(_CONFIG_STUB, encoding="utf-8")
        typer.echo(f"Created {stub.name}")
    cfg = Config.load(config)
    for name in cfg.names:
        folder = cfg.migrations_path / name
        folder.mkdir(parents=True, exist_ok=True)
        typer.echo(f"Ready: {folder}")


@migrations_app.command()
@handle_errors
def make(
    message: Annotated[str, typer.Argument(help="Short description, used in the file name.")],
    db: DbOption = None,
    empty: Annotated[
        bool, typer.Option("--empty", help="Write a blank revision instead of autogenerating.")
    ] = False,
    use_async: Annotated[
        bool, typer.Option("--async", help="Write `async def upgrade()` using `aop`.")
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Autogenerate a revision for every database whose models changed."""
    app = load_app(config)
    names = select_databases(app, db)
    if empty and len(names) > 1:
        raise ConfigError("--empty needs --db NAME when several databases are configured.")

    async def go() -> list[tuple[str, object]]:
        return [
            (
                name,
                await app.migrator(name).make_revision(message, empty=empty, use_async=use_async),
            )
            for name in names
        ]

    for name, path in run(app, go()):
        if path is None:
            typer.echo(f"{name}: no changes")
        else:
            typer.secho(f"{name}: created {path}", fg=typer.colors.GREEN)


@migrations_app.command()
@handle_errors
def history(db: DbOption = None, config: ConfigOption = None) -> None:
    """Show each chain from base to head. `*` = applied, `>` = current."""
    app = load_app(config)
    names = select_databases(app, db)

    async def go() -> list[tuple[str, list[tuple[object, bool]]]]:
        return [(name, await app.migrator(name).history()) for name in names]

    for name, rows in run(app, go()):
        typer.secho(f"[{name}]", bold=True)
        if not rows:
            typer.echo("  (no revisions)")
        last_applied = max((i for i, (_, applied) in enumerate(rows) if applied), default=-1)
        for i, (rev, applied) in enumerate(rows):
            marker = ">" if i == last_applied else ("*" if applied else " ")
            typer.echo(f"  {marker} {rev.id}  {rev.message}")  # type: ignore[attr-defined]


@migrations_app.command()
@handle_errors
def heads(db: DbOption = None, config: ConfigOption = None) -> None:
    """Print the head revision of each database (works offline)."""
    app = load_app(config)
    for name in select_databases(app, db):
        typer.echo(f"{name}: {short(app.migrator(name).chain.head)}")


@migrations_app.command()
@handle_errors
def check(
    db: DbOption = None,
    offline: Annotated[
        bool, typer.Option("--offline", help="Only validate chains; don't diff against databases.")
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Exit non-zero if a chain is broken or models have changes without a revision (for CI)."""
    app = load_app(config)
    names = select_databases(app, db)
    failed = False
    for name in names:
        chain = app.migrator(name).chain
        for warning in chain.warnings:
            typer.secho(f"{name}: warning: {warning}", fg=typer.colors.YELLOW)
        try:
            chain.validate()
        except ChainError as exc:
            typer.secho(str(exc), fg=typer.colors.RED, err=True)
            failed = True
    if not offline and not failed:

        async def go() -> list[tuple[str, bool]]:
            return [(name, await app.migrator(name).pending_changes()) for name in names]

        for name, pending in run(app, go()):
            if pending:
                typer.secho(
                    f"{name}: models changed but no revision exists. Run `migrations make`.",
                    fg=typer.colors.RED,
                    err=True,
                )
                failed = True
    if failed:
        raise typer.Exit(1)
    typer.secho("OK", fg=typer.colors.GREEN)


@migrations_app.command()
@handle_errors
def rechain(
    db: DbOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show changes only.")] = False,
    config: ConfigOption = None,
) -> None:
    """Re-link unapplied revisions in timestamp order (fixes branches after a git merge)."""
    app = load_app(config)
    names = select_databases(app, db)

    async def go() -> list[tuple[str, list[tuple[object, object, object]]]]:
        out = []
        for name in names:
            migrator = app.migrator(name)
            applied = await migrator.current()
            out.append((name, migrator.chain.rechain(applied, dry_run=dry_run)))
        return out

    for name, changes in run(app, go()):
        if not changes:
            typer.echo(f"{name}: chain already linear")
        for rev, old, new in changes:
            verb = "would re-link" if dry_run else "re-linked"
            typer.echo(f"{name}: {verb} {rev.id}: {short(old)} -> {short(new)}")  # type: ignore[attr-defined]
