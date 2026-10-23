# Third-party notices and credits

SynAlchemy is MIT licensed (see `LICENSE`). It does **not** vendor, fork, or copy
source code from any of the projects below. They are either installed as regular
dependencies or credited as design inspiration.

## Runtime dependencies

| Project | License | Used for |
|---|---|---|
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | MIT | ORM, async engines and sessions, the greenlet bridge used by async migrations |
| [Alembic](https://github.com/sqlalchemy/alembic) | MIT | Schema comparison (autogenerate), operation rendering, and the `op.*` migration operations |
| [Typer](https://github.com/fastapi/typer) | MIT | The `migrations`, `migrate` and `synalchemy` command-line interfaces |
| [tomli](https://github.com/hukkin/tomli) (Python < 3.11 only) | MIT | Reading TOML configuration |

Optional database drivers (`asyncpg`, `psycopg`, `aiosqlite`, `aiomysql`/PyMySQL,
`aioodbc`/pyodbc, `oracledb`) are installed only when you ask for them through an
extra, and keep their own licenses.

Each dependency's copyright and license text ships inside its own distribution.

## Design inspiration (no code copied)

| Project | License | Idea we drew on |
|---|---|---|
| [alembic-postgresql-enum](https://github.com/Pogchamp-company/alembic-postgresql-enum) | MIT | Detecting PostgreSQL ENUM value changes during autogenerate, and rendering columns with `create_type=False` so types are managed by explicit operations |
| [Flask-Migrate](https://github.com/miguelgrinberg/Flask-Migrate) | MIT | Running migrations per database "bind" from one project |
| [Advanced Alchemy](https://github.com/litestar-org/advanced-alchemy) | MIT | Async-first configuration and multi-engine ergonomics |
| [Aerich](https://github.com/tortoise/aerich) | Apache-2.0 | An async-first migration CLI experience |
| [SQLModel](https://github.com/fastapi/sqlmodel) | MIT | Developer-experience ideas for declaring models |
| Django migrations, Flask-SQLAlchemy `__bind_key__` | BSD-3-Clause | The split between creating migrations and applying them, and a per-model database key |

Thank you to the authors and maintainers of all of these projects.
