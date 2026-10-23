"""Shared plumbing for the CLIs."""

from __future__ import annotations

import asyncio
import functools
import importlib
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

import typer
from sqlalchemy.exc import SQLAlchemyError

from synalchemy.config import Config
from synalchemy.core import SynAlchemy
from synalchemy.exceptions import ConfigError, SynAlchemyError

T = TypeVar("T")

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        "-c",
        help="Config file (synalchemy.toml or pyproject.toml). Default: auto-detect in cwd.",
        envvar="SYNALCHEMY_CONFIG",
    ),
]
DbOption = Annotated[
    list[str] | None,
    typer.Option("--db", "-d", help="Database name; repeat for several. Default: all."),
]


def import_string(path: str) -> Any:
    module_name, _, attr = path.partition(":")
    obj: Any = importlib.import_module(module_name)
    for part in filter(None, attr.split(".")):
        obj = getattr(obj, part)
    return obj


def load_app(config_path: Path | None) -> SynAlchemy:
    """Build the SynAlchemy instance the CLI works on and import the models."""
    config = Config.load(config_path)
    root = str(config.root)
    if root not in sys.path:
        sys.path.insert(0, root)
    if config.app:
        app = import_string(config.app)
        if not isinstance(app, SynAlchemy):
            raise ConfigError(f"'app' = {config.app!r} is not a SynAlchemy instance.")
        for module in app.config.models:
            importlib.import_module(module)
        return app
    for module in config.models:
        importlib.import_module(module)
    metadata = import_string(config.metadata) if config.metadata else None
    return SynAlchemy(config=config, metadata=metadata)


def select_databases(app: SynAlchemy, names: list[str] | None) -> list[str]:
    if not names:
        return app.names
    for name in names:
        app.config.database(name)
    return list(dict.fromkeys(names))


def run(app: SynAlchemy, coro: Awaitable[T]) -> T:
    async def main() -> T:
        try:
            return await coro
        finally:
            await app.dispose()

    return asyncio.run(main())


def handle_errors(fn: Callable[..., T]) -> Callable[..., T]:
    """Print SynAlchemy and database errors cleanly instead of a traceback."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return fn(*args, **kwargs)
        except (SynAlchemyError, SQLAlchemyError) as exc:
            typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(1) from None

    return wrapper


def short(revision: str | None) -> str:
    return revision or "<base>"
