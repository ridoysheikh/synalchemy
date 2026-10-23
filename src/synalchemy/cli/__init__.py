"""Command-line entry points: ``migrations``, ``migrate`` and ``synalchemy``."""

from __future__ import annotations

import typer

from synalchemy import __version__
from synalchemy.cli.migrate import migrate_app
from synalchemy.cli.migrations import migrations_app

app = typer.Typer(
    name="synalchemy",
    help="SynAlchemy: async multi-database migrations for SQLAlchemy.",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(migrations_app, name="migrations")
app.add_typer(migrate_app, name="migrate")


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(__version__)


__all__ = ["app", "migrate_app", "migrations_app"]
