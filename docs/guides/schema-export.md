# Sharing the schema with other services

Your SynAlchemy project owns the schema: it holds the models and runs the migrations. Other services, in Go, JavaScript, plain Python or anything else, often read and write the same databases with their own libraries. They never migrate. Their risk is a **schema mismatch**: code written for columns that have since changed.

SynAlchemy can write one JSON file per database that describes its tables, stamped with the revision it matches. Other services build their models from that file and check the stamp against the database. Turning the JSON into code (structs, types, classes) is up to each service. SynAlchemy only writes the file.

## Turn it on

```toml
[schema]
export = true      # rewrite the files on every `migrations make`
dir = "schema"     # one <db>.json per database, relative to the config file
```

From then on, `migrations make` rewrites `schema/<db>.json` after it writes revisions, and so does `migrations rechain`, because it can move the head. Commit the files with the revisions they match.

To rebuild them any time (lost, stale, or written before you turned this on):

```bash
migrations export                       # every database, into [schema] dir
migrations export --db billing --out /tmp/schema
```

`migrations export` works offline and runs whether or not `export = true` is set. It reads the models and the head revision file, so run `migrations check` first if you aren't sure the models match the revisions.

## The file

```json
{
  "format": "synalchemy.schema/1",
  "database": "default",
  "dialect": "postgresql",
  "revision": "20261030T091500Z_c3d4",
  "version_table": "synalchemy_version",
  "fingerprint": "sha256:67aa…",
  "enums": [{ "name": "user_status", "schema": null, "values": ["active", "banned"], "native": true }],
  "tables": [
    {
      "name": "users",
      "schema": null,
      "comment": null,
      "columns": [
        {
          "name": "email",
          "type": "VARCHAR(255)",
          "kind": "string",
          "nullable": false,
          "primary_key": false,
          "autoincrement": false,
          "length": 255,
          "server_default": null,
          "client_default": null,
          "computed": null,
          "comment": null
        }
      ],
      "primary_key": ["id"],
      "foreign_keys": [{ "name": null, "columns": ["org_id"], "references": { "table": "orgs", "schema": null, "columns": ["id"] }, "on_delete": "CASCADE", "on_update": null }],
      "unique": [{ "name": null, "columns": ["public_id"] }],
      "indexes": [{ "name": "ix_users_email", "columns": ["email"], "unique": false }],
      "checks": [{ "name": "balance_positive", "sql": "balance >= 0" }]
    }
  ]
}
```

**Top level**

| Key | Meaning |
| --- | --- |
| `format` | `synalchemy.schema/1`. The number changes only if the layout changes in a way that breaks readers |
| `database`, `dialect` | the database name in the config, and its backend: `postgresql`, `mysql`, `sqlite`, `mssql`, `oracle`… |
| `revision` | the head revision these tables match; `null` before the first revision |
| `version_table` | the table in that database that holds its current revision (one row, column `version_num`) |
| `fingerprint` | a hash of `enums` and `tables` only. It changes when the schema changes, not when only the revision does (a data migration) |
| `enums` | the named ENUM types the tables use |
| `tables` | sorted by schema and name |

**Columns.** Every column has the keys shown above. `type` is the SQL type for this dialect; `kind` is a dialect-neutral one to map to your language:

| `kind` | Extra keys |
| --- | --- |
| `smallint`, `integer`, `bigint`, `boolean`, `float`, `uuid`, `date`, `interval`, `binary`, `json` | – |
| `string` | `length` (`null` = unlimited, e.g. `TEXT`) |
| `decimal` | `precision`, `scale` |
| `datetime`, `time` | `timezone` |
| `enum` | `enum`: `name`, `schema`, `values`, `native` (`false`: stored as `VARCHAR`, the values aren't enforced by the database) |
| `array` | `item`: `type`, `kind` |
| `other` | anything else; read `type` |

**Defaults.** `server_default` is SQL the database runs, such as `now()`, so you can leave the column out of an `INSERT`. `client_default` is set by the Python app, not the database. **Your service must supply this value itself when it inserts**:

| `client_default` | Means |
| --- | --- |
| `{"value": "active"}` | a fixed value (an ENUM member is given as its value) |
| `{"callable": "uuid4"}` | a Python function's result; produce the same in your language |
| `{"sql": "…"}` | a SQL expression the app sends with the `INSERT` |
| `{"sequence": "orders_id_seq"}` | the next value of this sequence |

`autoincrement: true` marks the column the database numbers by itself. A constraint `name` of `null` means the database chose the name.

Tables that migrations ignore (`exclude_tables`, and the version table) aren't listed.

## Checking for a mismatch in your service

At startup, read the database's current revision and compare it with the file's:

```sql
SELECT version_num FROM synalchemy_version
```

Revision ids start with a UTC timestamp, so plain string comparison orders them:

| Database revision vs. file `revision` | Means | Do |
| --- | --- | --- |
| equal | the database is exactly what the file describes | run |
| greater | the database was migrated after this file was made | warn, or refuse to start (strict) |
| less, or the table is missing | the database is behind your service's code | refuse to start |

Pick "warn" for "greater" if the Python project adds columns before removing old ones (below): a newer database still has everything your service uses. Pick "refuse" if any change may break you.

To save a lookup, the file names the table in `version_table`. Read the file once at build time (to generate code) or at startup (to check the revision); don't read it on each request.

## Keeping other services working through a change

Other services update later than the Python project, so make each migration safe for code that hasn't caught up:

1. **Expand.** Add new tables and columns as nullable or with a server default. Old services keep working.
2. **Update** the other services to the new `schema/<db>.json`.
3. **Contract.** Remove or rename the old columns in a later migration.

## Getting the files to other services

Pick whatever fits your setup:

- commit `schema/` and let other repos fetch it (a git submodule, or a raw-file URL pinned to a tag);
- have CI publish it as a release asset or package on each merge that changes it;
- copy it into each service's build in a monorepo.
