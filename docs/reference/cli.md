# CLI reference

| Command | Job |
| --- | --- |
| `migrations` | create and inspect revision files. Never changes a schema (it may read databases to compare). |
| `migrate` | apply revisions to databases |

Both also run as `synalchemy migrations …`, `synalchemy migrate …` and `python -m synalchemy …`.

**Every command accepts:**

| Option | Meaning |
| --- | --- |
| `--config PATH`, `-c` | config file (default: auto-detect in the current folder; env `SYNALCHEMY_CONFIG`) |
| `--db NAME`, `-d` | only this database; repeat for several (default: all) |

**Revision references** can be a full id (`20261024T091500Z_c3d4`), a unique prefix (`20261024T09`), `head` (latest) or `base` (before the first revision).

**Errors** print one `Error: …` line and exit with code 1.

## migrations

| Command | Does |
| --- | --- |
| `migrations init` | writes `synalchemy.toml` (if there's no config) and `migrations/<db>/` folders |
| `migrations make "msg"` | compares models with each database and writes a revision where they differ |
| `  --empty` | blank revision to fill in by hand (needs `--db` when there are several databases) |
| `  --async` | writes `async def upgrade()` with `await aop.*` |
| `migrations history` | each chain, oldest first: `*` applied, `>` current |
| `migrations heads` | latest revision per database (files only, no connection) |
| `migrations check` | exits 1 if a chain is broken or models changed without a revision |
| `  --offline` | check the chains only, without connecting |
| `migrations rechain` | re-links unapplied revisions in timestamp order |
| `  --dry-run` | show the changes only |
| `migrations export` | writes `<db>.json` [schema files](../guides/schema-export.md) from the models and head revision (offline) |
| `  --out DIR`, `-o` | write there instead of `[schema] dir` |

With `[schema] export = true`, `make` and `rechain` also rewrite the schema files.

## migrate

| Command | Does |
| --- | --- |
| `migrate` / `migrate up` | upgrades every database to head (creates missing ones if configured) |
| `  --parallel` | migrate databases concurrently |
| `  --sql [--from REV]` | print SQL instead of running it |
| `migrate down [N]` | reverts the last N revisions (default 1) |
| `migrate to REV` | goes up or down to `REV`; needs `--db` with several databases, except for `head` / `base` |
| `migrate status` | current revision, head and pending count per database |

## Examples

```bash
migrations make "add phone"                 # every database that changed
migrations make "backfill" --empty --db default
migrate                                     # all databases to head
migrate down --db analytics                 # analytics back by one
migrate to base --db default                # empty default's schema
migrate up --sql --db billing > billing.sql
migrations check                            # in CI
migrations export                           # rebuild schema/<db>.json
```
