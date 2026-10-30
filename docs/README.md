# SynAlchemy documentation

Each page answers one question and stays short. Find what you want to do below and follow the link. For anything SynAlchemy doesn't change, such as queries, relationships and `op.*` details, the [SQLAlchemy](https://docs.sqlalchemy.org/en/20/) and [Alembic](https://alembic.sqlalchemy.org/en/latest/) docs apply as they are.

> **New here?** Read [Install](getting-started/install.md), then [Quickstart](getting-started/quickstart.md).

## I want to…

### Get started

| …do this | Read |
| --- | --- |
| install SynAlchemy and a database driver | [Install](getting-started/install.md) |
| go from zero to a migrated database in five minutes | [Quickstart](getting-started/quickstart.md) |
| see a realistic app on three databases | [`test-preview/`](../test-preview/README.md) |

### Use it in an app

| …do this | Read |
| --- | --- |
| configure databases, URLs and environment variables | [Configuration](guides/configuration.md) |
| put a model in a non-default database | [Databases and routing](guides/databases-and-routing.md) |
| query from async code, sync code or raw SQL | [Databases and routing › Sessions](guides/databases-and-routing.md#sessions) |
| understand why a JOIN across databases is refused | [Databases and routing › Across databases](guides/databases-and-routing.md#across-databases) |
| read settings from a `.env` file | [Configuration › A `.env` file](guides/configuration.md#a-env-file) |
| choose a connection pool, or use sync engines | [Engines and pools](guides/engines-and-pools.md) |
| run behind PgBouncer or on serverless | [Engines and pools › Choose a pool](guides/engines-and-pools.md#choose-a-pool) |
| wire it into FastAPI or another framework | [Engines and pools › App lifecycle](guides/engines-and-pools.md#app-lifecycle) |

### Change the schema

| …do this | Read |
| --- | --- |
| create and apply migrations | [Migrations](guides/migrations.md) |
| write a data migration or an async revision | [Migrations › Hand-written revisions](guides/migrations.md#hand-written-revisions) |
| fix "has several children" after a git merge | [Migrations › Branches](guides/migrations.md#branches-after-a-git-merge) |
| add, remove or rename ENUM values | [ENUMs](guides/enums.md) |
| know what differs between PostgreSQL, MySQL, SQLite… | [Dialects](guides/dialects.md) |
| let services in Go, JavaScript… use the same databases without a mismatch | [Sharing the schema](guides/schema-export.md) |

### Look something up

| …do this | Read |
| --- | --- |
| every `migrations` / `migrate` command and flag | [CLI reference](reference/cli.md) |
| every config key | [Configuration › All keys](guides/configuration.md#all-keys) |
| the Python API (`SynAlchemy`, `Migrator`, helpers) | [Python API](reference/python-api.md) |

### Work on SynAlchemy

| …do this | Read |
| --- | --- |
| run the tests, including real database servers | [Testing](development/testing.md) |
| cut a release | [Releasing](development/releasing.md) |
