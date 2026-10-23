# Configuration

## Where config comes from

Later sources override earlier ones:

1. **File:** `synalchemy.toml` (top level), or `[tool.synalchemy]` in `pyproject.toml`, in the current folder. Use `--config PATH` or `SYNALCHEMY_CONFIG` to point elsewhere.
2. **Environment variables** (below).
3. **Code:** `SynAlchemy.from_config(databases={...}, ...)`, or skip files entirely with `SynAlchemy({"default": "sqlite:///app.db"})`.

A database named `default` is required. Any other name, such as `analytics` or `billing`, is yours to choose.

## Environment variables in values

Any string in the file can use:

| Write | Means |
| --- | --- |
| `"${DATABASE_URL}"` | the variable's value; an error if it isn't set |
| `"${DATABASE_URL:-sqlite:///./app.db}"` | the variable's value, or the text after `:-` if it isn't set |

This lets one file work on a laptop (the fallback) and in production (the variable).

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
exclude_tables = ["spatial_ref_sys"]

[engine_defaults]                # every database, unless it overrides
pool = "queue"
pool_size = 10

[databases.default]
url = "${DATABASE_URL}"

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
| `pool` | `auto`, `queue`, `null`, `static` or `single` ([Engines and pools](engines-and-pools.md)) |
| `create_if_missing` | create the database on first connect (not on Oracle) |
| anything else | passed to SQLAlchemy's [`create_engine`](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.create_engine): `pool_size`, `echo`, `connect_args`, `isolation_level`, … |
