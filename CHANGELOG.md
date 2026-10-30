# Changelog

All notable changes are listed here. Versions follow [semantic versioning](https://semver.org); until 1.0, minor versions may contain breaking changes, and each entry says how to upgrade.

## [0.3.0]

Nothing to change when upgrading: schema export is off until you set `[schema] export = true`.

### Added

- **Schema export for other services.** With `[schema] export = true`, `migrations make` (and `rechain`) writes `schema/<db>.json`: every table, column, key, index and ENUM, stamped with the head revision and a fingerprint. Services in other languages build their models from it and compare the stamp with the database's version table to catch a mismatch. `migrations export` rebuilds the files on demand, offline. See [Sharing the schema](docs/guides/schema-export.md).

## [0.2.0]

From the first real-world app. Nothing to change when upgrading, except two behaviour fixes: `${VAR:-fallback}` now also falls back when `VAR` is set but empty, and a relative SQLite path in a config file is relative to that file, not the current folder.

### Added

- **`from synalchemy import db`**: the instance your config file describes, built on first use. Importing it reads nothing. The CLIs use the same instance; `db.use(instance)` swaps in your own, `db.reset()` forgets it.
- **`env_file = ".env"`**: variables are read from that file too, so the app and the CLIs share settings without loading it themselves. The real environment wins.
- **`pool = "external"`** for transaction poolers (PgBouncer, Supabase / Neon poolers, RDS Proxy): no app-side pool, and the driver's prepared-statement caches off (asyncpg, psycopg).
- **`migration_url`** per database: migrations go to the direct endpoint while the app uses the pooler.
- **Serverless detection**: `pool = "auto"` is unpooled on AWS Lambda, Vercel, Netlify, Google Cloud Functions and Azure Functions.
- **Typed values from variables**: `pool_size = "${DB_POOL_SIZE:-5}"`, `echo = "${SQL_ECHO:-false}"` and the other pool options get their real type.

### Fixed

- `FastAPI(lifespan=db.lifespan)` failed at startup: `lifespan` yielded the instance, which Starlette took as the app's state. It yields nothing now.
- A relative SQLite file (`sqlite:///./app.db`) is relative to the config file, like `migrations_dir`, so the app and the CLIs open the same file from any folder. Configs built in code are relative to the current folder, as before.

### Changed

- The config file is also looked for in parent folders, so commands work from a subfolder.
- `${VAR:-fallback}` uses the fallback when `VAR` is empty, as the shell does. Empty `sync_url`, `migration_url` and `pool` mean "not set".
- `metadata = "module:attr"` is honoured by `SynAlchemy.from_config()`, not only by the CLIs.

## [0.1.0]

The first release.

### Added

- **Several databases, one model base.** A `default` database plus any number of named ones. `__db_name__ = "analytics"` on a model, or `info={"db_name": ...}` on a Core table, puts it in that database. `Model` is ready to use; `DBNameMixin` adds the same to your own base.
- **One session for all databases.** `db.session()` (async) and `db.sync_session()` (sync) send each statement to its tables' database. `bind_arguments={"db_name": ...}` chooses one for raw SQL. Statements and foreign keys that cross databases are refused with a clear error.
- **Engines and pools.** Async, sync and unpooled migration engines are created on first use. Choose `pool = "auto" | "queue" | "null" | "static" | "single"` per database or in `[engine_defaults]`. You get `pool_pre_ping` (except SQLite), hourly recycling on MySQL, and a shared connection for in-memory SQLite. The sync engine's URL is derived from the async one, or set with `sync_url`. `db.pool_status()` reports every pool.
- **Every major dialect.** PostgreSQL, MySQL, MariaDB, SQLite, SQL Server and Oracle, with the async driver filled in from a plain URL. `create_if_missing` creates databases on PostgreSQL, MySQL/MariaDB, SQL Server and SQLite.
- **Configuration** from `synalchemy.toml`, `[tool.synalchemy]` in `pyproject.toml`, environment variables (`SYNALCHEMY_DB_<NAME>_URL`, `DATABASE_URL`, …) and code, with `${VAR:-fallback}` in any value.
- **Migrations per database.** Revision ids start with a UTC timestamp, so files sort in creation order. Each database's chain is checked on every command, and `migrations rechain` fixes branches after a git merge without touching applied revisions.
- **Async migration runner.** Revisions run on the async driver, one transaction each. A database lock (`pg_advisory_lock`, `GET_LOCK`, `sp_getapplock`) stops overlapping `migrate` runs. Hand-written revisions can await with `run_async()`, or be fully `async def` with `aop`.
- **ENUM changes on every dialect.** PostgreSQL gets `op.create_enum`, `op.drop_enum` and `op.sync_enum_values`: add, remove and reorder values, and `renames=` to convert rows. Columns, arrays and defaults are converted along. MySQL/MariaDB get an ALTER when values or their order change; VARCHAR-backed dialects widen the column when needed.
- **Two CLIs.** `migrations` (`init`, `make`, `history`, `heads`, `check`, `rechain`) writes and inspects files. `migrate` (`up`, `down N`, `to REV`, `status`, `--sql`, `--parallel`) changes databases. Both are also available as `synalchemy …` and `python -m synalchemy …`.
- **Documentation** in `docs/`, and a runnable example on three databases in `test-preview/`.
