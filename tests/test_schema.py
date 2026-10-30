from __future__ import annotations

import enum
import json
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from synalchemy import Config, DBNameMixin, SynAlchemy, schema
from synalchemy.cli import migrate_app, migrations_app
from synalchemy.exceptions import ConfigError
from tests.test_cli import MODELS, invoke


class Status(enum.Enum):
    active = "active"
    banned = "banned"


def rich_metadata() -> sa.MetaData:
    class Base(DBNameMixin, DeclarativeBase):
        metadata = sa.MetaData(naming_convention={"ix": "ix_%(column_0_label)s"})

    class User(Base):
        __tablename__ = "users"
        __table_args__ = (sa.CheckConstraint("balance >= 0", name="balance_positive"),)
        id: Mapped[int] = mapped_column(primary_key=True)
        public_id: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, unique=True)
        email: Mapped[str] = mapped_column(sa.String(255), index=True)
        status: Mapped[Status] = mapped_column(
            sa.Enum(Status, name="user_status"), default=Status.active
        )
        balance: Mapped[float] = mapped_column(sa.Numeric(12, 2), server_default="0")

    class Order(Base):
        __tablename__ = "orders"
        id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
        user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id", ondelete="CASCADE"))

    class Event(Base):
        __tablename__ = "events"
        __db_name__ = "analytics"
        id: Mapped[int] = mapped_column(primary_key=True)

    return Base.metadata


@pytest.fixture
def app(tmp_path: Path) -> SynAlchemy:
    config = Config(
        databases={"default": "postgresql://u:p@h/db", "analytics": "sqlite:///a.db"},
        root=tmp_path,
    )
    return SynAlchemy(config=config, metadata=rich_metadata())


def test_build_describes_tables(app: SynAlchemy) -> None:
    out = schema.build(app, "default")
    assert out["format"] == schema.FORMAT
    assert (out["database"], out["dialect"], out["revision"]) == ("default", "postgresql", None)
    assert [t["name"] for t in out["tables"]] == ["orders", "users"]
    assert out["enums"] == [
        {"name": "user_status", "schema": None, "values": ["active", "banned"], "native": True}
    ]

    users = out["tables"][1]
    cols = {c["name"]: c for c in users["columns"]}
    assert cols["id"]["autoincrement"] and cols["id"]["primary_key"]
    email = {"type": "VARCHAR(255)", "kind": "string", "length": 255}
    assert cols["email"].items() >= email.items()
    assert cols["public_id"]["client_default"] == {"callable": "uuid4"}
    assert cols["status"]["client_default"] == {"value": "active"}
    assert cols["balance"]["server_default"] == "0"
    assert (cols["balance"]["precision"], cols["balance"]["scale"]) == (12, 2)
    assert users["indexes"] == [{"name": "ix_users_email", "columns": ["email"], "unique": False}]
    assert users["unique"] == [{"name": None, "columns": ["public_id"]}]
    assert users["checks"] == [{"name": "balance_positive", "sql": "balance >= 0"}]

    fk = out["tables"][0]["foreign_keys"][0]
    assert fk["references"] == {"table": "users", "schema": None, "columns": ["id"]}
    assert fk["on_delete"] == "CASCADE"


def test_fingerprint_is_stable(app: SynAlchemy, tmp_path: Path) -> None:
    first = schema.build(app, "default")
    assert schema.build(app, "default") == first
    assert schema.build(app, "analytics")["fingerprint"] != first["fingerprint"]
    [path] = schema.export(app, ["analytics"])
    assert path == tmp_path / "schema" / "analytics.json"
    assert json.loads(path.read_text())["tables"][0]["name"] == "events"


def crowded_metadata() -> sa.MetaData:
    """A table whose constraints and indexes are unnamed: only their columns tell them apart."""

    class Base(DBNameMixin, DeclarativeBase):
        pass

    class Store(Base):
        __tablename__ = "stores"
        id: Mapped[int] = mapped_column(primary_key=True)

    class Variant(Base):
        __tablename__ = "variants"
        id: Mapped[int] = mapped_column(primary_key=True)

    class User(Base):
        __tablename__ = "users"
        id: Mapped[int] = mapped_column(primary_key=True)

    class Batch(Base):
        __tablename__ = "batches"
        __table_args__ = (
            sa.UniqueConstraint("a", "b"),
            sa.UniqueConstraint("c", "d"),
            sa.UniqueConstraint("a", "d"),
            sa.Index(None, "a", "c"),
            sa.Index(None, "b", "d"),
            sa.Index(None, "d"),
        )
        id: Mapped[int] = mapped_column(primary_key=True)
        store_id: Mapped[int] = mapped_column(sa.ForeignKey("stores.id"))
        variant_id: Mapped[int] = mapped_column(sa.ForeignKey("variants.id"))
        user_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
        owner_id: Mapped[int] = mapped_column(sa.ForeignKey("users.id"))
        a: Mapped[int]
        b: Mapped[int]
        c: Mapped[int]
        d: Mapped[int]

    return Base.metadata


def test_unnamed_constraints_come_out_in_one_order(tmp_path: Path) -> None:
    """Foreign keys, unique constraints and indexes without a name used to tie in the sort, and a
    set decided their order: the same models exported twice gave two fingerprints."""
    config = Config(databases={"default": "sqlite:///a.db"}, root=tmp_path)
    seen = set()
    for _ in range(40):
        doc = schema.build(SynAlchemy(config=config, metadata=crowded_metadata()), "default")
        seen.add(doc["fingerprint"])
    assert len(seen) == 1
    table = next(t for t in doc["tables"] if t["name"] == "batches")
    foreign = [f["columns"] for f in table["foreign_keys"]]
    assert foreign == [["owner_id"], ["store_id"], ["user_id"], ["variant_id"]]
    assert [u["columns"] for u in table["unique"]] == [["a", "b"], ["a", "d"], ["c", "d"]]
    assert [i["columns"] for i in table["indexes"]] == [["a", "c"], ["b", "d"], ["d"]]


def test_schema_config(tmp_path: Path) -> None:
    config = Config.from_mapping(
        {"databases": {"default": "sqlite://"}, "schema": {"export": "yes", "dir": "out"}},
        root=tmp_path,
    )
    assert config.schema.export is True
    assert config.schema.path == tmp_path / "out"
    assert Config(databases={"default": "sqlite://"}).schema.export is False
    with pytest.raises(ConfigError, match="Unknown \\[schema\\]"):
        Config.from_mapping({"databases": {"default": "sqlite://"}, "schema": {"exprot": True}})


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str]:
    module = f"schema_models_{uuid.uuid4().hex[:8]}"
    (tmp_path / f"{module}.py").write_text(MODELS.format(extra=""))
    (tmp_path / "synalchemy.toml").write_text(
        f"""
models = ["{module}"]
metadata = "{module}:Base.metadata"
[databases]
default = "sqlite:///main.db"
analytics = "sqlite:///analytics.db"
[schema]
export = true
"""
    )
    monkeypatch.chdir(tmp_path)
    for var in ("SYNALCHEMY_CONFIG", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return tmp_path, module


def read(root: Path, name: str) -> dict:
    return json.loads((root / "schema" / f"{name}.json").read_text())


def test_make_exports_with_head_revision(project: tuple[Path, str]) -> None:
    root, module = project
    out = invoke(migrations_app, "make", "initial")
    assert "schema: wrote" in out
    [rev] = (root / "migrations" / "default").glob("*.py")
    first = read(root, "default")
    assert rev.name.startswith(first["revision"])

    invoke(migrate_app)
    (root / f"{module}.py").write_text(MODELS.format(extra="name: Mapped[str | None]"))
    sys.modules.pop(module, None)
    invoke(migrations_app, "make", "add name", "--db", "default")
    second = read(root, "default")
    assert second["revision"] > first["revision"]
    assert second["fingerprint"] != first["fingerprint"]
    assert "name" in [c["name"] for c in second["tables"][0]["columns"]]


def test_export_command_rebuilds_files(project: tuple[Path, str]) -> None:
    root, _ = project
    invoke(migrations_app, "make", "initial")
    before = read(root, "analytics")
    (root / "schema" / "analytics.json").unlink()

    out = invoke(migrations_app, "export", "--db", "analytics", "--out", "elsewhere")
    assert "elsewhere" in out and not (root / "schema" / "analytics.json").exists()
    invoke(migrations_app, "export")
    assert read(root, "analytics") == before


def test_make_skips_export_when_off(project: tuple[Path, str]) -> None:
    root, _ = project
    toml = root / "synalchemy.toml"
    toml.write_text(toml.read_text().replace("export = true", "export = false"))
    assert "schema:" not in invoke(migrations_app, "make", "initial")
    assert not (root / "schema").exists()
