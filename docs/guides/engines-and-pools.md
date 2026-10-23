# Engines and pools

## Three engines per database

All are created the first time they're used:

| Engine | Get it with | Pool | Used by |
| --- | --- | --- | --- |
| async | `db.engine(name)` | from `pool` | `db.session()` |
| sync | `db.sync_engine(name)` | from `pool` | `db.sync_session()`: scripts, Celery, threads |
| migration | `db.migration_engine(name)` | none (`NullPool`) | the CLIs, so they never take app connections |

The sync engine's URL comes from `sync_url`, or is derived from the async one:

| async | sync |
| --- | --- |
| asyncpg | psycopg, or psycopg2 (install `synalchemy[postgres-sync]`) |
| aiomysql / asyncmy | pymysql |
| aiosqlite | sqlite3 |
| aioodbc | pyodbc |
| oracledb, psycopg | same driver |

## Choose a pool

Set `pool` per database, or once in `[engine_defaults]`:

| `pool` | Pool class | Use it for |
| --- | --- | --- |
| `auto` (default) | the dialect's default | most apps |
| `queue` | `QueuePool` / `AsyncAdaptedQueuePool` | long-running servers; tune `pool_size`, `max_overflow`, `pool_timeout` |
| `null` | `NullPool` | CLIs, serverless, external poolers (PgBouncer, ProxySQL) |
| `static` | `StaticPool` | one shared connection, such as in-memory SQLite in tests |
| `single` | `SingletonThreadPool` (sync only) | one connection per thread |

**Defaults you get without asking:**
- `pool_pre_ping = true` everywhere except SQLite: dead connections are replaced instead of failing a request.
- `pool_recycle = 3600` on MySQL/MariaDB, to stay under the server's `wait_timeout`.
- In-memory SQLite always uses `static`, so every connection sees the same data.

Options a pool doesn't accept (such as `pool_size` with `null`) are dropped, so switching `pool` never breaks the config. Every other option is SQLAlchemy's: see [Connection pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html).

`db.pool_status()` shows every live pool.

## App lifecycle

```python
app = FastAPI(lifespan=db.lifespan)      # connect on startup, dispose on shutdown
```

Or by hand: `await db.connect()` creates missing databases and checks each one answers; `await db.dispose()` closes every pool. Code with no event loop can call `db.dispose_sync()`.
