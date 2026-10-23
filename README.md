# SynAlchemy

Async multi-database toolkit for **SQLAlchemy 2.x**.

- **Several databases, one model base.** `__db_name__ = "analytics"` puts a model in that database.
- **Engines and pools handled for you.** Async, sync and migration engines are created on first use, with the pool you choose.
- **One session for all of them.** Every query goes to the right database.
- **Async migrations per database.** Timestamped, strictly linear revision files, with `migrations` to write them and `migrate` to apply them.
- **ENUM changes migrated on every dialect.**
- **PostgreSQL, MySQL, MariaDB, SQLite, SQL Server and Oracle.**

Built on SQLAlchemy and Alembic, as dependencies. Nothing is forked.

## Install

```bash
pip install "synalchemy[postgres]"      # or sqlite, mysql, mssql, oracle
```

Until it's on PyPI, install from a [GitHub release](https://github.com/ridoysheikh/synalchemy/releases):

```bash
pip install "synalchemy[postgres] @ https://github.com/ridoysheikh/synalchemy/releases/download/v0.1.0/synalchemy-0.1.0-py3-none-any.whl"
```

## In five minutes

```toml
# synalchemy.toml
models = ["app.models"]

[databases]
default = "${DATABASE_URL:-sqlite:///./app.db}"
analytics = "sqlite:///./analytics.db"
```

```python
# app/models.py
from sqlalchemy.orm import Mapped, mapped_column
from synalchemy import Model

class User(Model):                 # -> default
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)

class Event(Model):                # -> analytics
    __tablename__ = "events"
    __db_name__ = "analytics"
    id: Mapped[int] = mapped_column(primary_key=True)
```

```bash
migrations make "initial"          # one revision file per database
migrate                            # apply to every database
```

```python
from synalchemy import SynAlchemy

db = SynAlchemy.from_config()
async with db.session() as session:
    session.add_all([User(), Event()])     # two databases, one session
    await session.commit()
```

To see it all running, try [`test-preview/`](test-preview/README.md): a shop on three databases, with a step-by-step walkthrough.

## Documentation

Short pages, one question each. Start at **[docs/](docs/README.md)**.

| | |
| --- | --- |
| [Install](docs/getting-started/install.md) · [Quickstart](docs/getting-started/quickstart.md) | get going |
| [Configuration](docs/guides/configuration.md) · [Databases and routing](docs/guides/databases-and-routing.md) · [Engines and pools](docs/guides/engines-and-pools.md) | use it in an app |
| [Migrations](docs/guides/migrations.md) · [ENUMs](docs/guides/enums.md) · [Dialects](docs/guides/dialects.md) | change the schema |
| [CLI](docs/reference/cli.md) · [Python API](docs/reference/python-api.md) | reference |

Queries, relationships and `op.*` work as in [SQLAlchemy](https://docs.sqlalchemy.org/en/20/) and [Alembic](https://alembic.sqlalchemy.org/en/latest/).

## Credits

Built on [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) and [Alembic](https://github.com/sqlalchemy/alembic) (MIT). Ideas from alembic-postgresql-enum, Flask-Migrate, Advanced Alchemy, Aerich, SQLModel and Django; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## License

[MIT](LICENSE)
