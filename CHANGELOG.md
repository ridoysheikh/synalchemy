# Changelog

All notable changes are listed here. Versions follow [semantic versioning](https://semver.org); until 1.0, minor versions may contain breaking changes, and each entry says how to upgrade.

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
