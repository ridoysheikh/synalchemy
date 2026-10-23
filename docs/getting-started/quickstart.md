# Quickstart

## 1. Configure

```bash
migrations init          # writes synalchemy.toml and migrations/<db>/ folders
```

Edit `synalchemy.toml`:

```toml
models = ["app.models"]

[databases]
default = "${DATABASE_URL:-sqlite:///./app.db}"
analytics = "sqlite:///./analytics.db"
```

`${VAR:-fallback}` reads an environment variable, with a fallback. See [Configuration](../guides/configuration.md).

## 2. Declare models

```python
# app/models.py
from sqlalchemy.orm import Mapped, mapped_column
from synalchemy import Model

class User(Model):                 # -> default
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

class Event(Model):                # -> analytics
    __tablename__ = "events"
    __db_name__ = "analytics"
    id: Mapped[int] = mapped_column(primary_key=True)
```

## 3. Create and apply migrations

```bash
migrations make "initial"      # one revision file per database that changed
migrate                        # apply them to every database
migrate status
```

## 4. Use it

```python
from synalchemy import SynAlchemy
from app.models import User, Event

db = SynAlchemy.from_config()

async def main():
    async with db.session() as session:          # one session, routed per model
        session.add_all([User(name="ada"), Event()])
        await session.commit()
    await db.dispose()
```

## Next

- [Databases and routing](../guides/databases-and-routing.md): how a model picks its database.
- [Migrations](../guides/migrations.md): the day-to-day workflow.
- [`test-preview/`](../../test-preview/README.md): a full example to run.
