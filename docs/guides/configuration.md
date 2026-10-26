# Configuration

## Where config comes from

Later sources override earlier ones:

1. **File:** `synalchemy.toml` (top level), or `[tool.synalchemy]` in `pyproject.toml`, in the current folder or the nearest parent. Use `--config PATH` or `SYNALCHEMY_CONFIG` to point elsewhere. Relative paths (`migrations_dir`, `env_file`, SQLite files such as `sqlite:///./app.db`) are relative to the file.
2. **Environment variables** (below).
3. **Code:** `SynAlchemy.from_config(databases={...}, ...)`, or skip files entirely with `SynAlchemy({"default": "sqlite:///app.db"})`.

A database named `default` is required. Any other name, such as `analytics` or `billing`, is yours to choose.

## Environment variables in values

Any string in the file can use:

| Write | Means |
| --- | --- |
| `"${DATABASE_URL}"` | the variable's value; an error if it isn't set |
| `"${DATABASE_URL:-sqlite:///./app.db}"` | the variable's value, or the text after `:-` if it is unset **or empty** (as in the shell) |
| `"${DB_DIRECT_URL:-}"` | the value, or "not set" (`sync_url`, `migration_url` and `pool` treat empty as unset) |

This lets one file work on a laptop (the fallback) and in production (the variable).

Numbers and switches can come from variables too: `pool_size = "${DB_POOL_SIZE:-5}"` becomes `5`, and `echo = "${SQL_ECHO:-false}"` becomes `False` (`pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`, `echo`, `echo_pool`, `pool_pre_ping`, `pool_use_lifo`, `create_if_missing`).

## A `.env` file

```toml
env_file = ".env"
```

Values are read from that file as well as from the environment, so the CLIs and the app see the same settings without loading it themselves. The real environment wins, so production can leave the file out. `KEY=value` lines, `#` comments, `export` and quotes are understood; a missing file is fine. The file only feeds the config: it isn't copied into `os.environ`.

## Environment variables that override the file

| Variable | Sets |
| --- | --- |
| `SYNALCHEMY_DB_<NAME>_URL` | the URL of database `<name>`, e.g. `SYNALCHEMY_DB_ANALYTICS_URL` |
| `DATABASE_URL` | `default`'s URL, if nothing else sets it |
| `SYNALCHEMY_MODELS` | `models`, comma-separated |
| `SYNALCHEMY_APP`, `SYNALCHEMY_MIGRATIONS_DIR` | `app`, `migrations_dir` |
| `SYNALCHEMY_CONFIG` | which config file to read |

## A full example

```toml
models = ["app.models"]
migrations_dir = "migrations"
env_file = ".env"
exclude_tables = ["spatial_ref_sys"]

[engine_defaults]                # every database, unless it overrides
pool = "${DB_POOL:-queue}"       # "external" in production, behind PgBouncer
pool_size = "${DB_POOL_SIZE:-10}"

[databases.default]
url = "${DATABASE_URL}"
migration_url = "${DATABASE_DIRECT_URL:-}"   # migrations skip the pooler

[databases.analytics]
url = "mysql://app:pw@db2/analytics"
pool = "null"
create_if_missing = true
```

A database can also be a single string: `analytics = "sqlite:///a.db"`.

## All keys

**Top level**

| Key | Default | Meaning |
| --- | --- | --- |
| `databases` | required | name → URL string, or a table (below) |
| `models` | `[]` | modules the CLI imports so every model is registered |
| `env_file` | – | a `.env` file to read variables from; the real environment wins |
| `app` | – | `"module:attr"` of your own `SynAlchemy` instance; the CLI then uses it |
| `metadata` | `Model.metadata` | `"module:attr"` of your `MetaData`, if you use your own declarative base |
| `migrations_dir` | `migrations` | one sub-folder per database |
| `version_table` | `synalchemy_version` | stores the current revision, in each database |
| `exclude_tables` | `[]` | glob patterns of tables migrations ignore |
| `engine_defaults` | `{}` | engine options and `pool` for every database |

**Per database**

| Key | Meaning |
| --- | --- |
| `url` | the database URL; the async driver is filled in ([Install](../getting-started/install.md)) |
| `sync_url` | URL for the sync engine; derived from `url` when unset |
| `migration_url` | URL the CLIs migrate through, unpooled; `url` when unset. Point it at the direct endpoint when `url` is a pooler |
| `pool` | `auto`, `queue`, `null`, `external`, `static` or `single` ([Engines and pools](engines-and-pools.md)) |
| `create_if_missing` | create the database on first connect (not on Oracle) |
| anything else | passed to SQLAlchemy's [`create_engine`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.create_engine): `pool_size`, `echo`, `connect_args`, `isolation_level`, … |
