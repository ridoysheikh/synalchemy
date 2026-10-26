# Engines and pools

## Three engines per database

All are created the first time they're used:

| Engine | Get it with | Pool | Used by |
| --- | --- | --- | --- |
| async | `db.engine(name)` | from `pool` | `db.session()` |
| sync | `db.sync_engine(name)` | from `pool` | `db.sync_session()`: scripts, Celery, threads |
| migration | `db.migration_engine(name)` | none (`NullPool`) | the CLIs, so they never take app connections; on `migration_url` when set |

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
| `auto` (default) | the dialect's default; `NullPool` on serverless platforms | most apps |
| `queue` | `QueuePool` / `AsyncAdaptedQueuePool` | long-running servers; tune `pool_size`, `max_overflow`, `pool_timeout` |
| `null` | `NullPool` | CLIs, scripts, serverless |
| `external` | `NullPool`, and no prepared-statement cache in the driver | behind a transaction pooler: PgBouncer, Supabase / Neon poolers, RDS Proxy, ProxySQL |
| `static` | `StaticPool` | one shared connection, such as in-memory SQLite in tests |
| `single` | `SingletonThreadPool` (sync only) | one connection per thread |

**Defaults you get without asking:**
- `pool_pre_ping = true` everywhere except SQLite: dead connections are replaced instead of failing a request.
- `pool_recycle = 3600` on MySQL/MariaDB, to stay under the server's `wait_timeout`.
- In-memory SQLite always uses `static`, so every connection sees the same data.

**Serverless.** On AWS Lambda, Vercel, Netlify, Google Cloud Functions and Azure Functions (detected from `AWS_LAMBDA_FUNCTION_NAME`, `VERCEL`, `NETLIFY`, `FUNCTION_TARGET`, `FUNCTIONS_WORKER_RUNTIME`), `auto` opens a connection per checkout: a frozen instance's idle connections would go stale. An explicit `pool` always wins.

**Behind a pooler.** A transaction pooler gives every transaction a different server connection, so a prepared statement made on one isn't there on the next. `external` switches the driver's caches off (asyncpg: `statement_cache_size=0`, `prepared_statement_cache_size=0`; psycopg: `prepare_threshold=None`) and leaves pooling to the pooler. Your own `connect_args` still apply on top. Migrations take `migrate`'s lock for a whole session, which a transaction pooler can't keep, so give them the direct endpoint with `migration_url`:

```toml
[databases.default]
url = "${DATABASE_URL}"                        # the pooler
migration_url = "${DATABASE_DIRECT_URL:-}"     # the server itself
pool = "${DB_POOL:-queue}"                     # DB_POOL=external in production
```

Options a pool doesn't accept (such as `pool_size` with `null`) are dropped, so switching `pool` never breaks the config. Every other option is SQLAlchemy's: see [Connection pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html).

`db.pool_status()` shows every live pool.

## App lifecycle

```python
from synalchemy import db

app = FastAPI(lifespan=db.lifespan)      # connect on startup, dispose on shutdown
```

Or by hand: `await db.connect()` creates missing databases and checks each one answers; `await db.dispose()` closes every pool. Code with no event loop can call `db.dispose_sync()`.
