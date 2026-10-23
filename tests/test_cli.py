from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from synalchemy.cli import app, migrate_app, migrations_app

runner = CliRunner()

MODELS = """
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from synalchemy import DBNameMixin

class Base(DBNameMixin, DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    {extra}

class Event(Base):
    __tablename__ = "events"
    __db_name__ = "analytics"
    id: Mapped[int] = mapped_column(primary_key=True)
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    module = f"cli_models_{uuid.uuid4().hex[:8]}"
    (tmp_path / f"{module}.py").write_text(MODELS.format(extra=""))
    (tmp_path / "synalchemy.toml").write_text(
        f"""
models = ["{module}"]
metadata = "{module}:Base.metadata"
[databases]
default = "sqlite:///main.db"
analytics = "sqlite:///analytics.db"
"""
    )
    monkeypatch.chdir(tmp_path)
    for var in ("SYNALCHEMY_CONFIG", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, module


def invoke(cli, *args: str):
    result = runner.invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_cli_round_trip(project: tuple[Path, str]) -> None:
    root, _ = project
    out = invoke(migrations_app, "make", "initial")
    assert "default: created" in out and "analytics: created" in out
    assert len(list((root / "migrations" / "default").glob("*.py"))) == 1

    out = invoke(migrate_app)
    assert "default: <base> ->" in out
    assert "up to date" in invoke(migrate_app, "status")
    assert "OK" in invoke(migrations_app, "check")
    assert "no changes" in invoke(migrations_app, "make", "again")
    assert ">" in invoke(migrations_app, "history")
    assert "default: 2026" in invoke(migrations_app, "heads") or "default:" in invoke(
        migrations_app, "heads"
    )

    out = invoke(migrate_app, "down", "--db", "default")
    assert "down" in out
    assert "1 pending" in invoke(migrate_app, "status", "--db", "default")
    invoke(migrate_app, "up", "--db", "default")
    assert "1 pending" not in invoke(migrate_app, "status")

    sql = invoke(migrate_app, "up", "--sql", "--db", "default")
    assert "CREATE TABLE users" in sql

    assert "chain already linear" in invoke(migrations_app, "rechain")


def test_check_fails_on_unmigrated_changes(project: tuple[Path, str]) -> None:
    root, module = project
    invoke(migrations_app, "make", "initial")
    invoke(migrate_app)
    (root / f"{module}.py").write_text(MODELS.format(extra="name: Mapped[str | None]"))
    import sys

    sys.modules.pop(module, None)
    result = runner.invoke(migrations_app, ["check"])
    assert result.exit_code == 1
    assert "models changed" in result.output


def test_errors_are_clean(project: tuple[Path, str]) -> None:
    result = runner.invoke(migrate_app, ["status", "--db", "nope"])
    assert result.exit_code == 1
    assert "Unknown database 'nope'" in result.output
    result = runner.invoke(migrations_app, ["make", "x", "--empty"])
    assert result.exit_code == 1
    assert "--db NAME" in result.output


def test_init_writes_stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SYNALCHEMY_CONFIG", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = invoke(migrations_app, "init")
    assert "Created synalchemy.toml" in out
    assert (tmp_path / "migrations" / "default").is_dir()
    assert invoke(app, "version").strip()
