# FastAPI example

A FastAPI app with no database setup code. `synalchemy.toml` holds the database, its pool and the migration endpoint, and `from synalchemy import db` gives the app and the CLIs the same instance.

```bash
pip install "synalchemy[postgres,sqlite]" fastapi uvicorn
migrations make "initial" && migrate
uvicorn main:app
```

With nothing set it runs on SQLite. Copy `.env.example` to `.env` to switch to PostgreSQL. `DB_POOL` picks the pool:

| `DB_POOL` | For |
| --- | --- |
| `auto` (default) | the driver's pool; unpooled on serverless platforms |
| `queue` | a long-running server: `DB_POOL_SIZE` connections kept open |
| `null` | scripts and cron jobs: one connection per checkout |
| `external` | behind PgBouncer or a managed pooler; set `DATABASE_DIRECT_URL` so migrations bypass it |

See [Engines and pools](../../docs/guides/engines-and-pools.md).
