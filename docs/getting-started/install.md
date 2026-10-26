# Install

SynAlchemy needs Python 3.10+. Install it with the extra for each database you use:

```bash
pip install "synalchemy[postgres]"
pip install "synalchemy[postgres,sqlite]"     # several at once
```

Until it's on PyPI, install a release from GitHub:

```bash
pip install "synalchemy[postgres] @ https://github.com/ridoysheikh/synalchemy/releases/download/v0.2.0/synalchemy-0.2.0-py3-none-any.whl"
```

| Extra | Installs | You write URLs like |
| --- | --- | --- |
| `postgres` | asyncpg | `postgresql://user:pw@host/db` |
| `postgres-sync` | psycopg (only needed for [sync engines](../guides/engines-and-pools.md) on PostgreSQL) | – |
| `mysql` | aiomysql + PyMySQL (needs SQLAlchemy 2.0.50+) | `mysql://…`, `mariadb://…` |
| `sqlite` | aiosqlite | `sqlite:///app.db` |
| `mssql` | aioodbc + pyodbc. Also install Microsoft's [ODBC Driver 18](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server). | `mssql://user:pw@host/db?driver=ODBC+Driver+18+for+SQL+Server` |
| `oracle` | python-oracledb (one driver for async and sync) | `oracle://user:pw@host:1521/?service_name=FREEPDB1` |

You never write the async driver yourself. `postgresql://` becomes `postgresql+asyncpg://`, and so on. An explicit driver, such as `postgresql+psycopg://`, is kept as is.

Installing SynAlchemy gives you three commands: `migrations`, `migrate`, and `synalchemy` (which holds both). `python -m synalchemy` works too.

Next: [Quickstart](quickstart.md).
