# SynAlchemy — Plan

> **Status: v0.1.0 implemented.** Changes from the plan below:
> - Open questions answered: the config and migration designs stay as planned; `__db_name__`; **all dialects** (PostgreSQL, MySQL, MariaDB, SQLite, SQL Server, Oracle); **`down N` instead of `undo`**, so there's no run-log table.
> - Added an engine layer: async, sync and unpooled migration engines, with pool kinds `auto`/`queue`/`null`/`static`/`single` and `engine_defaults`. See README "Engines and pools".
> - `migrations merge` was **dropped**. Chains are strictly linear and `rechain` is the only fix for branches, which keeps the model simpler.
> - Alembic is used only as a library: autogenerate, ops and rendering. Revision loading, the chain, version tables and the runner are SynAlchemy's own. No `alembic.ini`, `env.py` or Mako template.
> - ENUM ops are inserted after `produce_migrations` instead of through Alembic's comparator registry, which changed in Alembic 1.20. This works the same on Alembic 1.13+.
> - Minimum versions: Python 3.10, SQLAlchemy 2.0.30 (2.0.50 with the `mysql` extra), Alembic 1.13, Typer 0.13. All are tested.

An async SQLAlchemy 2.x wrapper that handles **multiple databases**, **automatic engine creation**, and **async migrations** (including ENUM changes), with two separate CLIs: `migrations` and `migrate`.

SQLAlchemy and Alembic are used as normal dependencies. Nothing is forked.

---

## 1. Goals

| # | Requirement | How it's met |
|---|---|---|
| 1 | Multi-DB: one `default` plus any number of named DBs | Config maps `name -> URL`. A model sets `__db_name__ = "analytics"`; without it, the model goes to `default`. |
| 2 | Engines are created automatically | Lazy `EngineRegistry`: the first time a DB is used, its `AsyncEngine` is built from config. It can also create the database if it doesn't exist yet. |
| 3 | Fully async | `create_async_engine`, `AsyncSession`, and migrations run through `AsyncConnection.run_sync()`. Async data-migration helpers are included. |
| 4 | Migrations auto-applied to every DB | Each DB gets its own version chain and version table. `migrate` runs all DBs, or only the ones you pick. |
| 5 | ENUM types update automatically | A custom autogenerate comparator detects added/removed/renamed values and emits the right DDL for each dialect. |
| 6 | Linear, chained revisions with timestamp filenames | Revision IDs and filenames start with a UTC timestamp. The chain is validated on every load (single root, single head, no gaps). `rechain` fixes branches. |
| 7 | Separate `migrations` and `migrate` CLIs | Two console scripts, similar to Django's `makemigrations` / `migrate`. |
| 8 | Upgrade/downgrade chain, undo at any time | `migrate up / down N / to REV / undo`. `undo` reverts the last `migrate` run using a small run log. |

**Non-goals (for v1):** cross-DB joins or foreign keys, distributed transactions (two-phase commit can be added later), a query DSL on top of SQLAlchemy.

---

## 2. Key decision: build on Alembic as a library

Writing our own schema differ (tables, columns, indexes, constraints, types for each dialect) would take months. Alembic (MIT) already does this well. We use it **programmatically**, so the user never sees `alembic.ini` or `env.py`:

- **From Alembic:** `autogenerate.compare_metadata` / `produce_migrations`, `Operations` (`op.*`), `MigrationContext`, and `ScriptDirectory` for loading revisions.
- **Ours:** config, engine registry, per-DB metadata partitioning, file naming and revision IDs, chain validation and rechaining, the ENUM comparator, the run log for undo, and both CLIs.

This is the "quick and simple" path. If we ever outgrow Alembic, the migration layer sits behind one internal interface (`synalchemy.migrations.backend`), so it can be replaced.

---

## 3. Public API (draft)

```python
from synalchemy import SynAlchemy, Model
from sqlalchemy.orm import Mapped, mapped_column

db = SynAlchemy.from_config()          # reads synalchemy.toml / pyproject / env
# or: SynAlchemy(databases={"default": "postgresql+asyncpg://...", "analytics": "..."})

class User(Model):                     # -> default DB
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)

class Event(Model):                    # -> analytics DB
    __tablename__ = "events"
    __db_name__ = "analytics"
    id: Mapped[int] = mapped_column(primary_key=True)

async with db.session() as s:          # one session, routed per model
    s.add_all([User(), Event()])
    await s.commit()

engine = db.engine("analytics")        # created lazily on first access
await db.dispose()                     # app shutdown
```

> **Why `__db_name__` and not `db_name`:** a plain `db_name` attribute would clash with any column called `db_name`. The dunder name follows SQLAlchemy's own convention (`__tablename__`). This is easy to change if you prefer otherwise.

### Internals

- **`Model`**: a declarative base. `__init_subclass__` reads `__db_name__` (default `"default"`), checks it against config, and stores it in `__table__.info["db_name"]`. There is one shared `MetaData`. For each DB, a filtered view is built when needed (`db.metadata_for("analytics")`).
- **Routing session**: a subclass of `Session` whose `get_bind(mapper, clause)` returns the engine for `mapper.local_table.info["db_name"]`, wrapped in `AsyncSession(sync_session_class=RoutingSession)`. A query that mixes models from two DBs raises a clear error.
- **`EngineRegistry`**: a dict of `name -> AsyncEngine`, built lazily under an `asyncio.Lock`. Each DB has its own engine options (pool size, echo, `connect_args`). Optional `create_database_if_missing` (PostgreSQL/MySQL: connect to the server DB and run `CREATE DATABASE`; SQLite: create the file).
- **Helpers**: `db.session_dependency()` for FastAPI/Starlette, `db.lifespan()` as an async context manager, and `db.create_all()` / `drop_all()` for each DB (for tests).

---

## 4. Configuration (proposal, still open)

Load order, where later sources override earlier ones: **`pyproject.toml [tool.synalchemy]` → `synalchemy.toml` → environment variables → Python kwargs**.

```toml
[tool.synalchemy]
models = ["app.models"]              # modules imported so all models get registered
migrations_dir = "migrations"

[tool.synalchemy.databases.default]
url = "${DATABASE_URL}"              # ${ENV} interpolation
pool_size = 10

[tool.synalchemy.databases.analytics]
url = "postgresql+asyncpg://u:p@host/analytics"
create_if_missing = true
```

Environment variable form: `SYNALCHEMY_DB_DEFAULT_URL=...` and `SYNALCHEMY_DB_ANALYTICS_URL=...`.
A `default` entry is required. Any other key is a named DB.

---

## 5. Migrations design

### 5.1 Layout on disk

```
migrations/
  default/
    20261023T143012Z_a1b2_create_users.py
    20261024T091500Z_c3d4_add_user_role.py
  analytics/
    20261023T143013Z_e5f6_create_events.py
```

- **Revision ID** = `YYYYMMDDTHHMMSSZ_<4 hex>` (UTC). The random suffix prevents collisions when two developers generate at the same second.
- **Filename** = `<revision>_<slug>.py`, so sorting by filename gives timestamp order.
- **Version table** per DB: `synalchemy_version` (configurable). There is also a `synalchemy_migration_log` table (see 5.5).

### 5.2 Revision file template

```python
"""add user role

Revision: 20261024T091500Z_c3d4
Revises:  20261023T143012Z_a1b2
Database: default
Created:  2026-10-24T09:15:00Z
"""
from synalchemy.migrations import op, run_async

revision = "20261024T091500Z_c3d4"
down_revision = "20261023T143012Z_a1b2"
db_name = "default"

def upgrade() -> None:
    op.add_column("users", sa.Column("role", sa.Enum("admin", "member", name="user_role")))

def downgrade() -> None:
    op.drop_column("users", "role")
```

### 5.3 Chain rules (checked on every CLI call)

1. Exactly one root (`down_revision = None`) and one head per DB.
2. Every `down_revision` exists, and there are no cycles.
3. Along the chain, timestamps must strictly increase. If not, we warn and point to `rechain`.
4. If two files share a parent (common after a git merge), we stop with a clear message and two choices:
   - `migrations rechain`: re-link the **unapplied** revisions in timestamp order by rewriting their `down_revision`. Applied revisions are never touched.
   - `migrations merge`: create an empty merge revision, for teams that prefer explicit merges.

### 5.4 Async execution

```python
async with engine.connect() as conn:
    await conn.run_sync(_run_alembic, target_rev, direction)
    await conn.commit()
```

- Migration bodies are written with normal `op.*` calls. They run inside `run_sync`, which already sits in SQLAlchemy's greenlet bridge, so the async driver (asyncpg, aiomysql, aiosqlite) is used from start to finish.
- **`run_async(coro_fn)`**: a helper (built on `sqlalchemy.util.await_only`) so that data migrations can `await` async code, such as an `AsyncSession` bound to the same connection.
- Several DBs can be migrated at once with `asyncio.gather` (`migrate --parallel`). The default is sequential, in config order, so output is easy to follow.
- By default, each revision runs in its own transaction. On PostgreSQL there is an option to run the whole batch in one transaction.

### 5.5 Undo

Every `migrate` call writes one row per DB to `synalchemy_migration_log`: `run_id, db_name, from_rev, to_rev, direction, at`.
`migrate undo` reads the latest `run_id` and moves each affected DB back to its `from_rev`. Running `undo` again steps back through earlier runs.

### 5.6 ENUM handling

Alembic does not detect changes to ENUM values on PostgreSQL. We register a comparator with `@comparators.dispatch_for("schema")` that:

- reflects existing enum types (`pg_enum`) for each DB and compares them with the `sa.Enum` types in that DB's metadata;
- emits custom operations (`SyncEnumValuesOp`, rendered in the revision file), with dialect-specific handling:

| Dialect | Add value | Remove/rename value |
|---|---|---|
| PostgreSQL | `ALTER TYPE … ADD VALUE` (on PG < 12 this runs in an autocommit block) | `ALTER TYPE … RENAME VALUE` for renames. Removals recreate the type: rename the old one, create the new one, `ALTER COLUMN … USING …::text::new`, drop the old one. |
| MySQL/MariaDB | `ALTER TABLE … MODIFY COLUMN` with the new `ENUM(...)` list (via `compare_type`) | same |
| SQLite | non-native enum → CHECK constraint, rebuilt with batch mode | same |

- New enum types are created only in the DBs whose tables use them, and are dropped when no table uses them anymore.
- A rename can't be told apart from a remove plus an add, so autogenerate writes a remove + add with a `# TODO: rename?` comment. `migrations make --enum-rename user_role:old=new` makes it explicit.
- Every operation generates its matching `downgrade()`.

---

## 6. CLIs

Both are installed as console scripts. They are also available as `synalchemy migrations …` / `synalchemy migrate …` in case the short names clash with other tools.

### `migrations` (writes files, never touches schema)

| Command | What it does |
|---|---|
| `migrations make "msg" [--db NAME] [--empty]` | Autogenerates a revision for each DB that has changes. `--empty` creates a blank revision for hand-written or data migrations. |
| `migrations history [--db NAME]` | Shows the chain in order and marks which revisions are applied. |
| `migrations heads` / `check` | Validates the chain. Exits non-zero if something is wrong (useful in CI). Also exits non-zero if models have changes with no migration file. |
| `migrations rechain [--db NAME]` | Re-links unapplied revisions in timestamp order. |
| `migrations merge [--db NAME]` | Creates an explicit merge revision. |
| `migrations init` | Creates `migrations/<db>/` for each configured DB, plus a config stub. |

### `migrate` (applies changes to the DB)

| Command | What it does |
|---|---|
| `migrate` / `migrate up [--db NAME]` | Upgrades every DB (or the selected one) to head. |
| `migrate down [N] [--db NAME]` | Goes back N revisions (default 1). |
| `migrate to REV --db NAME` | Moves to an exact revision, either up or down. |
| `migrate undo` | Reverts the last `migrate` run (see 5.5). |
| `migrate status` | Shows the current and head revision for each DB, plus how many are pending. |
| `--sql` | Prints the SQL instead of running it (offline mode). |
| `--parallel` | Migrates DBs concurrently. |

The CLI uses **Typer** (MIT), which is a thin layer over Click.

---

## 7. Package layout

```
synalchemy/
  __init__.py            # SynAlchemy, Model
  config.py              # loading, env interpolation, validation (pydantic-free, dataclasses)
  registry.py            # EngineRegistry, create_database_if_missing
  model.py               # declarative Base, __db_name__ partitioning
  session.py             # RoutingSession + AsyncSession factory
  integrations/fastapi.py
  migrations/
    backend.py           # thin interface over Alembic (Config/ScriptDirectory/context built in code)
    naming.py            # revision id + filename
    chain.py             # validation, rechain, merge
    autogen.py           # include_object per DB, comparators registration
    enums.py             # enum comparator + ops + renderers
    runner.py            # async run_sync orchestration, parallel, offline
    runlog.py            # synalchemy_migration_log / undo
    template.py.mako
  cli/
    migrations.py
    migrate.py
tests/                   # pytest + pytest-asyncio; Postgres/MySQL via testcontainers, SQLite in-process
pyproject.toml           # [project.scripts] migrations=…, migrate=…, synalchemy=…
```

**Dependencies:** `sqlalchemy>=2.0`, `alembic>=1.13`, `typer`, `tomli` (only on Python < 3.11).
**Optional drivers:** `asyncpg`, `aiomysql`/`asyncmy`, `aiosqlite`.
**Python:** 3.10+.

---

## 8. Milestones

1. **Core:** config loader, `EngineRegistry`, `Model` with `__db_name__`, routing `AsyncSession`, `create_all`. Tests on SQLite with two DBs.
2. **Migration backend:** programmatic Alembic, per-DB metadata filter, timestamp naming, template, `migrations make` and `migrate up/down/to/status`.
3. **Chain integrity:** validation, `check`, `rechain`, `merge`, `history`.
4. **Undo and run log:** `migrate undo`, `--parallel`, `--sql`.
5. **ENUM sync:** PostgreSQL first (add/rename/remove + downgrade), then MySQL and SQLite.
6. **Hardening:** test matrix (PG 13–17, MySQL 8, SQLite), FastAPI integration, docs, examples.

---

## 9. Open questions for you

1. **Config:** is `pyproject`/`synalchemy.toml` plus env OK, or would you rather use a Python settings object (e.g. pydantic-settings)?
2. **Dialects:** start with PostgreSQL only, or PostgreSQL + SQLite (+ MySQL) from day one?
3. **Attribute name:** `__db_name__` (recommended) or plain `db_name`?
4. **Undo semantics:** is "undo the last `migrate` run" right, or do you only need `down N`?
5. **Cross-DB:** should a model ever live in *more than one* DB (e.g. a shared lookup table copied to each)?

---

## 10. Credits / prior art

All projects below are used as dependencies or as design references only. No code is copied without attribution. Licenses should be re-checked before any code is adapted.

| Project | License | What we take from it |
|---|---|---|
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | MIT | Core ORM, async engine and session, greenlet bridge |
| [Alembic](https://github.com/sqlalchemy/alembic) | MIT | Autogenerate, ops, script directory; the `run_sync` async recipe; the multidb template |
| [alembic-postgresql-enum](https://github.com/Pogchamp-company/alembic-postgresql-enum) | MIT | Approach for detecting and syncing PostgreSQL ENUM values |
| [Flask-Migrate](https://github.com/miguelgrinberg/Flask-Migrate) | MIT | Multi-DB "binds" migration pattern |
| [Advanced Alchemy](https://github.com/litestar-org/advanced-alchemy) | MIT | Async config and multi-engine ergonomics, framework integrations |
| [Aerich](https://github.com/tortoise/aerich) | Apache-2.0 | Async-first migration CLI user experience |
| [SQLModel](https://github.com/fastapi/sqlmodel) | MIT | Developer-experience ideas for model declaration |
| Django migrations / Flask-SQLAlchemy `__bind_key__` | BSD-3 | Design inspiration only (the `makemigrations`/`migrate` split, the bind-key idea) |
