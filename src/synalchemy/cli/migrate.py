"""``migrate``: apply, revert and inspect migrations on the configured databases."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
from synalchemy.core import SynAlchemy
from synalchemy.exceptions import ConfigError
from synalchemy.migrations.chain import UP
from synalchemy.migrations.runner import Migrator, MoveResult

migrate_app = typer.Typer(
    name="migrate",
    help="Apply migrations. With no command, upgrades every database to head.",
    invoke_without_command=True,
    add_completion=False,
)

ParallelOption = Annotated[bool, typer.Option("--parallel", help="Migrate databases concurrently.")]


def _pick(sub: list[str] | None, ctx: typer.Context) -> list[str] | None:
    return sub or (ctx.obj or {}).get("db")


def _pick_config(sub: object, ctx: typer.Context) -> object:
    return sub or (ctx.obj or {}).get("config")


def _report(results: list[MoveResult]) -> None:
    for result in results:
        if not result.changed:
            typer.echo(f"{result.db_name}: nothing to do (at {short(result.from_rev)})")
            continue
        typer.secho(
            f"{result.db_name}: {short(result.from_rev)} -> {short(result.to_rev)}",
            fg=typer.colors.GREEN,
        )
        for revision, direction in result.steps:
            arrow = "up  " if direction == UP else "down"
            typer.echo(f"  {arrow} {revision.id}  {revision.message}")


def _move_all(
    app: SynAlchemy,
    names: list[str],
    action: Callable[[Migrator], Awaitable[MoveResult]],
    parallel: bool = False,
) -> None:
    async def go() -> list[MoveResult]:
        migrators = [app.migrator(name) for name in names]
        if parallel:
            return list(await asyncio.gather(*(action(m) for m in migrators)))
        return [await action(m) for m in migrators]

    _report(run(app, go()))


def _upgrade(
    config: object, db: list[str] | None, parallel: bool, sql: bool, from_rev: str | None
) -> None:
    app = load_app(config)  # type: ignore[arg-type]
    names = select_databases(app, db)
    if sql:
        for name in names:
            typer.echo(f"-- database: {name}")
            typer.echo(app.migrator(name).sql(from_rev, "head"))
        return
    _move_all(app, names, lambda m: m.upgrade(), parallel)


@migrate_app.callback()
@handle_errors
def main(
    ctx: typer.Context,
    db: DbOption = None,
    parallel: ParallelOption = False,
    sql: Annotated[bool, typer.Option("--sql", help="Print SQL instead of running it.")] = False,
    from_rev: Annotated[
        str | None, typer.Option("--from", help="Starting revision for --sql.")
    ] = None,
    config: ConfigOption = None,
) -> None:
    ctx.obj = {"db": db, "config": config}
    if ctx.invoked_subcommand is None:
        _upgrade(config, db, parallel, sql, from_rev)


@migrate_app.command()
@handle_errors
def up(
    ctx: typer.Context,
    db: DbOption = None,
    parallel: ParallelOption = False,
    sql: Annotated[bool, typer.Option("--sql", help="Print SQL instead of running it.")] = False,
    from_rev: Annotated[
        str | None, typer.Option("--from", help="Starting revision for --sql.")
    ] = None,
    config: ConfigOption = None,
) -> None:
    """Upgrade to head."""
    _upgrade(_pick_config(config, ctx), _pick(db, ctx), parallel, sql, from_rev)


@migrate_app.command()
@handle_errors
def down(
    ctx: typer.Context,
    steps: Annotated[int, typer.Argument(help="How many revisions to revert.")] = 1,
    db: DbOption = None,
    config: ConfigOption = None,
) -> None:
    """Revert the last N applied revisions (default 1)."""
    app = load_app(_pick_config(config, ctx))  # type: ignore[arg-type]
    _move_all(app, select_databases(app, _pick(db, ctx)), lambda m: m.downgrade(steps))


@migrate_app.command("to")
@handle_errors
def to(
    ctx: typer.Context,
    revision: Annotated[str, typer.Argument(help="Revision id or prefix, `head` or `base`.")],
    db: DbOption = None,
    config: ConfigOption = None,
) -> None:
    """Move one database up or down to an exact revision."""
    app = load_app(_pick_config(config, ctx))  # type: ignore[arg-type]
    names = select_databases(app, _pick(db, ctx))
    if len(names) > 1 and revision not in ("head", "base"):
        raise ConfigError("Revision ids belong to one database; pass --db NAME.")
    _move_all(app, names, lambda m: m.goto(revision))


@migrate_app.command()
@handle_errors
def status(ctx: typer.Context, db: DbOption = None, config: ConfigOption = None) -> None:
    """Show current revision, head and pending count for each database."""
    app = load_app(_pick_config(config, ctx))  # type: ignore[arg-type]
    names = select_databases(app, _pick(db, ctx))

    async def go() -> list:
        return [await app.migrator(name).status() for name in names]

    for item in run(app, go()):
        state = "up to date" if item.pending == 0 else f"{item.pending} pending"
        typer.echo(
            f"{item.db_name}: current {short(item.current)}, head {short(item.head)} ({state})"
        )
