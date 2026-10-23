# Python API

## `SynAlchemy`

```python
from synalchemy import SynAlchemy

db = SynAlchemy.from_config(path=None, *, metadata=None, session_options=None, **overrides)
db = SynAlchemy({"default": "postgresql://…", "analytics": {"url": "…", "pool": "null"}})
db = SynAlchemy(config=Config(...), metadata=Base.metadata)
```

| Member | Returns / does |
| --- | --- |
| `db.names` | configured database names, `"default"` first |
| `db.config` | the loaded `Config` |
| `db.engine(name="default")` | async engine, created on first use |
| `db.sync_engine(name="default")` | sync engine |
| `db.migration_engine(name="default")` | unpooled async engine used by migrations |
| `db.session(**kw)` | routing `AsyncSession` (`async with`) |
| `db.sync_session(**kw)` | routing `Session` (`with`) |
| `db.sessionmaker`, `db.sync_sessionmaker` | the underlying factories |
| `db.get_session()` | async generator for dependency injection |
| `await db.connect(*names)` | create missing databases, check each connects |
| `await db.dispose()` / `db.dispose_sync()` | close all pools / only sync pools |
| `db.lifespan(app=None)` | async context manager: connect, then dispose |
| `db.pool_status()` | `{name: status}` for every live pool |
| `db.metadata_for(name)` | a `MetaData` copy with only that database's tables |
| `await db.create_all(*names)` / `drop_all` | create or drop tables directly (tests) |
| `db.migrator(name="default")` | a `Migrator` |

Sessions default to `expire_on_commit=False`. Change it with `session_options`.

## `Migrator`

What the CLI uses, for scripts and tests:

```python
m = db.migrator("analytics")
await m.upgrade("head"); await m.downgrade(1); await m.goto("base")
await m.status()            # Status(db_name, current, head, pending)
await m.history()           # [(Revision, applied), ...]
await m.make_revision("msg", empty=False, use_async=False)   # Path, or None if no changes
m.sql(from_ref=None, to_ref="head")                          # offline SQL text
```

## Models

| Name | Use |
| --- | --- |
| `Model` | ready-made declarative base; set `__db_name__` on subclasses |
| `DBNameMixin` | add `__db_name__` support to your own base |
| `db_name_of(table)` | the database a table belongs to |

## In revision files (`synalchemy.migrations`)

| Name | Use |
| --- | --- |
| `op` | Alembic's `op`, plus `create_enum`, `drop_enum`, `sync_enum_values` |
| `run_async(fn, *args)` | from a sync revision, await `fn(conn, *args)` |
| `aop` | awaitable `op` for `async def upgrade()` |
| `get_connection()` | the revision's `AsyncConnection` |

## Errors

All derive from `SynAlchemyError`: `ConfigError`, `RoutingError`, `ChainError`, `MigrationError`.
