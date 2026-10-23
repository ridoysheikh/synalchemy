# Testing

```bash
uv sync                                   # dev environment
uv run ruff check src tests && uv run ruff format --check src tests
uv run pytest -q                          # SQLite only
```

## Against real servers

Each server's tests run when its URL is set and are skipped otherwise. Databases are created with random names and dropped afterwards.

| Variable | Example |
| --- | --- |
| `SYNALCHEMY_TEST_PG_URL` | `postgresql://test:test@127.0.0.1:55439/postgres` |
| `SYNALCHEMY_TEST_MYSQL_URL` | `mysql://root:test@127.0.0.1:55440/mysql` |
| `SYNALCHEMY_TEST_MARIADB_URL` | `mariadb://root:test@127.0.0.1:55441/mysql` |
| `SYNALCHEMY_TEST_MSSQL_URL` | `mssql+aioodbc://sa:Pw-123456@127.0.0.1:1433/master?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes` |
| `SYNALCHEMY_TEST_ORACLE_URL` | `oracle://syn:test@127.0.0.1:55442/?service_name=FREEPDB1` |

Throwaway servers:

```bash
docker run -d --rm --name syn-pg -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test -p 127.0.0.1:55439:5432 postgres:16-alpine
docker run -d --rm --name syn-mysql -e MYSQL_ROOT_PASSWORD=test -p 127.0.0.1:55440:3306 mysql:8.4
docker run -d --rm --name syn-mariadb -e MARIADB_ROOT_PASSWORD=test -p 127.0.0.1:55441:3306 mariadb:11.4
docker run -d --rm --name syn-oracle -e ORACLE_PASSWORD=test -e APP_USER=syn -e APP_USER_PASSWORD=test -p 127.0.0.1:55442:1521 gvenzl/oracle-free:23-slim-faststart
```

## What runs where

| Tests | Cover |
| --- | --- |
| `test_config`, `test_chain`, `test_engines`, `test_session` | units, always on SQLite |
| `test_migrations`, `test_cli` | the full migration lifecycle and both CLIs, on SQLite |
| `test_postgres` | ENUM sync in depth, database creation, advisory lock |
| `test_dialects` | the same lifecycle on every configured server |

CI (`.github/workflows/ci.yml`) runs lint, the suite on Python 3.10–3.14 with PostgreSQL, and `test_dialects` against MySQL, MariaDB, SQL Server and Oracle.
