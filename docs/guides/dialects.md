# Dialects

Everything works on every dialect. These are the differences worth knowing:

| | PostgreSQL | MySQL / MariaDB | SQLite | SQL Server | Oracle |
| --- | --- | --- | --- | --- | --- |
| Async driver (filled in) | asyncpg | aiomysql | aiosqlite | aioodbc | oracledb |
| A failed revision rolls back fully | yes | no¹ | yes | yes | no¹ |
| Lock against overlapping `migrate` | `pg_advisory_lock` | `GET_LOCK` | – ² | `sp_getapplock` | – |
| `create_if_missing` | yes | yes | yes (makes the folder) | yes | no |
| ENUMs | separate type | inline `ENUM` | `VARCHAR` | `VARCHAR` | `VARCHAR2` |
| ALTER limits | – | – | batch mode ³ | – | – |

1. DDL commits statement by statement. If a revision fails halfway, the statements before the failure stay applied, and the version doesn't move. Put the risky step first in hand-written revisions, and fix forward with a new revision.
2. SQLite locks the whole file while writing, so overlapping runs simply wait.
3. SQLite can't alter most columns in place. Generated revisions use Alembic's [batch mode](https://alembic.sqlalchemy.org/en/latest/batch.html) (`with op.batch_alter_table(...)`), which copies the table. `--async` revisions don't use batch mode.

## Notes per dialect

- **PostgreSQL:** sync engines need `synalchemy[postgres-sync]` (psycopg).
- **MySQL / MariaDB:** the `mysql` extra needs SQLAlchemy 2.0.50+. Connections recycle every hour by default, to stay under `wait_timeout`.
- **SQL Server:** install Microsoft's ODBC Driver 18 and pass `?driver=ODBC+Driver+18+for+SQL+Server` in the URL. Add `&TrustServerCertificate=yes` for local servers with self-signed certificates.
- **Oracle:** create the user or schema yourself. python-oracledb's thin mode needs no Oracle client.

Dialect-specific SQL types, options and quirks are SQLAlchemy's: see [Dialects](https://docs.sqlalchemy.org/en/20/dialects/).
