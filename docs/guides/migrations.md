# Migrations

## Daily workflow

```bash
# 1. change your models
migrations make "add phone to customers"   # 2. writes a revision per changed database
# 3. read the new file(s); adjust if needed
migrate                                    # 4. apply
```

Two commands, two jobs: `migrations` only writes and inspects files; `migrate` changes databases. Every flag is in the [CLI reference](../reference/cli.md).

## Revision files

```
migrations/
  default/20261024T091500Z_c3d4_add_phone.py
  analytics/20261024T091500Z_9f2a_add_phone.py
```

- The **name starts with a UTC timestamp**, so files sort in creation order. The 4 hex characters keep ids unique when two people generate in the same second.
- Each file has `revision`, `down_revision` (its parent), `db_name`, and `upgrade()` / `downgrade()`.
- Each database has **one linear chain**. Every command checks it: one start, one end, no gaps.
- `op.*` is Alembic's operations API, unchanged: see [Operation reference](https://alembic.sqlalchemy.org/en/latest/ops.html).

## Running them

- `migrate` takes every database to its latest revision. `migrate down N --db NAME` steps one database back; `migrate to REV --db NAME` goes to an exact revision.
- **Each revision runs in its own transaction.** On PostgreSQL, SQL Server and SQLite, a failing revision is rolled back completely. MySQL, MariaDB and Oracle commit DDL statement by statement; see [Dialects](dialects.md).
- **Overlapping runs are blocked.** Several app instances running `migrate` on deploy are safe: a database lock lets one through at a time.
- `migrations make` refuses while a database is behind its head. Run `migrate` first so the comparison is correct.

Autogenerate detects what Alembic detects (tables, columns, types, indexes, constraints), plus [ENUM values](enums.md). Renames look like a drop and an add, so read each file before applying. Alembic lists what it can and can't see: [What does autogenerate detect](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).

## Hand-written revisions

`migrations make "backfill" --empty --db default` writes a blank revision. Revisions run on the async driver, and you can await from them:

```python
from synalchemy.migrations import op, run_async

def upgrade() -> None:
    op.add_column("users", sa.Column("score", sa.Integer(), server_default="0"))
    run_async(backfill)

async def backfill(conn):              # the revision's AsyncConnection
    await conn.execute(sa.text("UPDATE users SET score = 1"))
```

Or write the whole revision async with `--async`:

```python
from synalchemy.migrations import aop, get_connection

async def upgrade() -> None:
    await aop.add_column("users", sa.Column("score", sa.Integer()))
    await get_connection().execute(sa.text("UPDATE users SET score = 0"))
```

## Branches after a git merge

If two people each created a revision on the same parent, commands stop with *"… has several children"*. Fix it with:

```bash
migrations rechain --dry-run     # shows what would change
migrations rechain
```

This re-links the **unapplied** revisions in timestamp order by rewriting their `down_revision`. Applied revisions are never touched.

## In CI and production

```bash
migrations check        # CI: exits 1 if a chain is broken, or models changed without a revision
migrate up --sql        # print SQL for review instead of running it
migrate                 # deploy
```
