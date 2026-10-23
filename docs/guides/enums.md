# ENUMs

Change the values in your model, run `migrations make`, and the revision updates the database. What it writes depends on how the dialect stores ENUMs:

| Dialect | Stored as | When values change, the revision has |
| --- | --- | --- |
| PostgreSQL | a separate type (`CREATE TYPE`) | `op.sync_enum_values(...)` |
| MySQL / MariaDB | part of the column (`ENUM('a','b')`) | `op.alter_column(..., type_=sa.Enum(...))`, also when only the **order** changes |
| SQLite, SQL Server, Oracle | `VARCHAR` sized to the longest value | `op.alter_column(...)` when a longer value needs more room |

## PostgreSQL

| Operation | Written when |
| --- | --- |
| `op.create_enum(name, values)` | a model uses a new ENUM type |
| `op.sync_enum_values(name, old, new)` | values were added, removed or reordered |
| `op.drop_enum(name, values)` | no column uses the type anymore |

- **Adding values** uses `ALTER TYPE … ADD VALUE`, keeping their position. A value added in a revision can't be used in that same revision; PostgreSQL 12+ is required.
- **Removing or reordering values** recreates the type and converts every column that uses it, including arrays and defaults.
- **If rows still use a removed value**, the revision fails and rolls back. Your data is safe.
- **To rename a value**, edit the generated line, because autogenerate can't tell a rename from a remove plus an add:

  ```python
  op.sync_enum_values("user_role", ["admin", "member"], ["admin", "guest"],
                      renames={"member": "guest"})
  ```
  Existing `member` rows become `guest`.

ENUM columns are written with `create_type=False`, so only these operations create and drop types.

## MySQL / MariaDB

Removing a value that rows still use fails (strict mode). To rename a value, edit the revision into three steps: add the new value, `UPDATE` the rows, then remove the old value.

## Not covered

`sa.Enum(..., create_constraint=True)` adds a CHECK constraint on non-native backends. Changes to that constraint aren't detected.
