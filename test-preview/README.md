# SynAlchemy test preview: a shop on three databases

A small, realistic app that shows SynAlchemy end to end:

| Database | Holds | Default | With Docker |
|---|---|---|---|
| `default` | customers, products, orders, order items | SQLite `data/shop.db` | PostgreSQL |
| `analytics` | click-stream events | SQLite `data/analytics.db` | MySQL |
| `billing` | payments | SQLite `data/billing.db` | SQLite |

## Run it

From the repository root, install the dev environment once:

```bash
uv sync
```

Then run the walkthrough on SQLite. Nothing else is needed:

```bash
cd test-preview
../.venv/bin/python walkthrough.py            # add --pause to go step by step
```

To run it on real servers (PostgreSQL + MySQL + SQLite):

```bash
docker compose up -d --wait
export SHOP_DB_URL=postgresql://shop:shop@127.0.0.1:55452/shop
export ANALYTICS_DB_URL=mysql://root:shop@127.0.0.1:55453/analytics
../.venv/bin/python walkthrough.py
docker compose down -v                        # when you're done
```

The `shop` and `analytics` databases don't need to exist; `create_if_missing = true` creates them.

## What the walkthrough does

Each step prints the exact command it runs, so you can repeat any of them by hand.

1. **`migrations make "initial schema"`** writes one revision file per database.
2. **`migrate`** creates the databases and applies them; **`migrate status`** shows the result.
3. **`python -m shop seed` / `order ...`**: one async session writes an order to `default`, its payment to `billing` and an event to `analytics`.
4. **`python -m shop report`**: a sync session (as a cron job would use) reads all three databases.
5. **`python -m shop cross-db`**: a JOIN across databases raises `RoutingError`; the fix is one query per database.
6. **Schema version 2** (`SHOP_SCHEMA_VERSION=2`) adds new ENUM values and columns. `migrations make` writes files for `default` and `analytics` only, since billing didn't change.
7. **The generated file** for `default` is printed. Compare dialects:
   - PostgreSQL: `op.sync_enum_values('order_status', ...)`
   - MySQL (`migrations/analytics/`): `op.alter_column(..., type_=sa.Enum(...))`
   - SQLite: a wider `VARCHAR`
8. **`migrate`** applies version 2.
9. **`migrate down 1 --db analytics`**, then **`migrate`**: one database steps back and forward on its own.
10. **`python -m shop refund 2`** uses the new `refunded` / `refund` values.
11. **Rollback safety:** going down while rows use a value being removed fails on PostgreSQL and MySQL, which protects your data.
12. **`migrations history`, `migrations check`, `migrate up --sql`, `python -m shop pools`.**

Afterwards, open `migrations/<database>/` to read every generated revision.

## Files

| File | What it shows |
|---|---|
| `synalchemy.toml` | Three databases, `${VAR:-fallback}` URLs, `engine_defaults` with a queue pool, and `pool = "null"` for analytics |
| `shop/models.py` | `__db_name__`, ENUMs, no foreign keys across databases |
| `shop/services.py` | Async sessions for requests, a sync session for reports, cross-database rules, pool status |
| `shop/__main__.py` | `python -m shop seed / order / refund / report / cross-db / pools` |
| `walkthrough.py` | Runs the story above |
| `docker-compose.yml` | PostgreSQL 16 + MySQL 8.4 on ports 55452 / 55453 |

In a real project you would edit `shop/models.py` directly instead of using `SHOP_SCHEMA_VERSION`; it only lets the walkthrough show "before" and "after" from one file.
