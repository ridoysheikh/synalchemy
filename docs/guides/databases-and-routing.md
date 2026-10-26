# Databases and routing

## Put a model in a database

```python
from synalchemy import Model

class Event(Model):
    __tablename__ = "events"
    __db_name__ = "analytics"      # a name from [databases]; leave it out for "default"
```

Keeping your own declarative base? Add the mixin:

```python
from sqlalchemy.orm import DeclarativeBase
from synalchemy import DBNameMixin

class Base(DBNameMixin, DeclarativeBase):
    pass
```

Then set `metadata = "app.models:Base.metadata"` in the config. Core tables opt in with `Table(..., info={"db_name": "analytics"})`.

Everything else about models is plain SQLAlchemy: see [Declarative mapping](https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html).

## Sessions

One session reaches every database. It picks the database from each statement's model or tables:

```python
async with db.session() as session:            # AsyncSession
    session.add_all([User(name="ada"), Event(kind="signup")])
    await session.commit()                     # commits each database in turn

with db.sync_session() as session:             # plain Session, for scripts and workers
    session.scalars(select(User)).all()
```

For SQL with no table, such as `text(...)`, choose the database explicitly:

```python
await session.execute(text("SELECT 1"), bind_arguments={"db_name": "analytics"})
```

`db` here is `from synalchemy import db`, or an instance you built yourself.

**For dependency injection** (FastAPI): `Depends(db.get_session)` yields a session per request.

Queries, loading and relationships work as usual: see [the ORM querying guide](https://docs.sqlalchemy.org/en/20/orm/queryguide/).

## Across databases

Databases on different servers can't see each other. So:

- **A statement that mixes databases** (a JOIN, or a subquery) raises `RoutingError` before anything is sent. Run one query per database and combine the results in Python.
- **A foreign key to another database's table** raises `ConfigError`. Store the id as a plain, indexed column and check it in code:

  ```python
  class Payment(Model):
      __db_name__ = "billing"
      order_id: Mapped[int] = mapped_column(index=True)   # orders live in "default"
  ```
- **A commit touching several databases** commits them one after another. It isn't a distributed transaction, so design writes so a partial failure is recoverable.
