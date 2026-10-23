"""Run the whole SynAlchemy story on a small shop, one real command at a time.

    python walkthrough.py            # fresh start: wipes ./data and ./migrations first
    python walkthrough.py --pause    # wait for Enter after each step

Every step prints the exact command it runs, so you can repeat any of them by hand.
Afterwards, open ./migrations/<database>/ to read the generated revision files.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOLD, DIM, CYAN, RESET = "\033[1m", "\033[2m", "\033[36m", "\033[0m"

STEPS: list[tuple[str, str, list[list[str]], int]] = [
    (
        "1. Generate the first migrations",
        "The models in shop/models.py are spread over three databases. `migrations make` "
        "compares each database with its models and writes one revision file per database. "
        "Nothing is applied yet.",
        [["migrations", "make", "initial schema"]],
        1,
    ),
    (
        "2. Apply them",
        "`migrate` upgrades every database to its head. Databases that don't exist yet are "
        "created first (create_if_missing = true).",
        [["migrate"], ["migrate", "status"]],
        1,
    ),
    (
        "3. Use the shop (async sessions)",
        "One session, three databases. An order goes to `default`, its payment to `billing`, "
        "and the checkout event to `analytics`. Routing comes from each model's __db_name__.",
        [
            ["shop", "seed"],
            ["shop", "order", "ada@example.com", "KB-01:1", "MS-02:2"],
            ["shop", "order", "alan@example.com", "MN-27:2", "--provider", "paypal"],
            ["shop", "order", "grace@example.com", "MS-02:1"],
        ],
        1,
    ),
    (
        "4. Nightly report (sync session)",
        "The same models used from plain sync code, for example a cron job. SynAlchemy builds "
        "a sync engine from each async URL (aiosqlite -> sqlite3, asyncpg -> psycopg, ...).",
        [["shop", "report"]],
        1,
    ),
    (
        "5. Cross-database queries are refused",
        "A JOIN between orders (default) and payments (billing) can't work. SynAlchemy raises "
        "RoutingError before sending anything; the fix is one query per database.",
        [["shop", "cross-db"]],
        1,
    ),
    (
        "6. A month later: the models change",
        "Schema version 2 adds `refunded` / `partially_refunded` to the order_status ENUM, a "
        "`refund` event kind, customers.phone and events.utm_source. Billing doesn't change, "
        "so it gets no new file.",
        [["migrations", "make", "refunds phone and utm"]],
        2,
    ),
    (
        "7. Read the generated revision for the default database",
        "Revision files start with a UTC timestamp, so they sort in creation order, and each "
        "one points at its parent (down_revision). On PostgreSQL this file uses "
        "op.sync_enum_values; on MySQL, an ALTER of the ENUM column; on SQLite, a wider VARCHAR.",
        [],
        2,
    ),
    (
        "8. Apply version 2",
        "",
        [["migrate"]],
        2,
    ),
    (
        "9. Step back and forward again",
        "`migrate down 1 --db analytics` reverts only the analytics database by one revision "
        "(utm_source disappears, `refund` leaves the ENUM). `migrate` brings it back.",
        [
            ["migrate", "down", "1", "--db", "analytics"],
            ["migrate", "status"],
            ["migrate"],
        ],
        2,
    ),
    (
        "10. Use the new ENUM values",
        "Refunding order #2 writes the new `refunded` status (default database) and a "
        "`refund` event (analytics).",
        [["shop", "refund", "2"], ["shop", "report"]],
        2,
    ),
    (
        "11. Rollbacks protect your data",
        "Going down now would remove the `refund` value while a refund event still uses it. "
        "PostgreSQL refuses and rolls the whole revision back. MySQL refuses the ALTER too; "
        "here it's the first statement, so nothing changed, but MySQL commits DDL one "
        "statement at a time, so keep risky steps first in hand-edited revisions. SQLite "
        "stores the ENUM as plain VARCHAR and allows it. `migrate` then returns to head.",
        [["!", "migrate", "down", "1", "--db", "analytics"], ["migrate"]],
        2,
    ),
    (
        "12. Inspect: history, CI check, offline SQL, pools",
        "`history` shows each chain (`>` = current). `check` exits non-zero if models changed "
        "without a revision, which is useful in CI. `--sql` prints SQL without running it. "
        "`pools` shows the pool each engine uses: queue for default and billing, null for "
        "analytics, as set in synalchemy.toml.",
        [
            ["migrations", "history"],
            ["migrations", "check"],
            ["migrate", "up", "--sql", "--db", "billing"],
            ["shop", "pools"],
        ],
        2,
    ),
]


def command_line(args: list[str]) -> tuple[list[str], str]:
    """Real argv plus the short form shown to the reader."""
    if args[0] == "shop":
        return [sys.executable, "-m", "shop", *args[1:]], "python -m shop " + " ".join(args[1:])
    return [sys.executable, "-m", "synalchemy", *args], " ".join(_quote(a) for a in args)


def _quote(arg: str) -> str:
    return f'"{arg}"' if " " in arg else arg


def run(args: list[str], version: int) -> None:
    may_fail = args[0] == "!"  # a step that is expected to fail on some dialects
    args = args[1:] if may_fail else args
    argv, shown = command_line(args)
    prefix = "SHOP_SCHEMA_VERSION=2 " if version == 2 else ""
    print(f"{CYAN}$ {prefix}{shown}{RESET}")
    env = {**os.environ, "SHOP_SCHEMA_VERSION": str(version), "PYTHONPATH": str(HERE)}
    result = subprocess.run(argv, cwd=HERE, env=env, text=True, capture_output=True)
    output = (result.stdout + result.stderr).rstrip()
    for line in output.splitlines():
        print(f"  {line}")
    if result.returncode != 0:
        print(f"  {DIM}(exit code {result.returncode}){RESET}")
        if not may_fail:
            raise SystemExit(f"step failed: {shown}")


def show_latest_revision(database: str) -> None:
    files = sorted((HERE / "migrations" / database).glob("*.py"))
    latest = files[-1]
    print(f"{CYAN}$ cat migrations/{database}/{latest.name}{RESET}")
    for line in latest.read_text().splitlines():
        print(f"  {DIM}|{RESET} {line}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pause", action="store_true", help="wait for Enter after each step")
    options = parser.parse_args()

    for folder in ("data", "migrations"):
        shutil.rmtree(HERE / folder, ignore_errors=True)
    urls = {k: os.environ.get(k, "sqlite (default)") for k in ("SHOP_DB_URL", "ANALYTICS_DB_URL")}
    print(
        f"{BOLD}SynAlchemy test preview{RESET}  shop={urls['SHOP_DB_URL']}  "
        f"analytics={urls['ANALYTICS_DB_URL']}  billing=sqlite"
    )
    if any("://" in u for u in urls.values()):
        print(
            f"{DIM}note: server databases keep their tables between runs; "
            f"`docker compose down -v` resets them{RESET}"
        )

    for title, explanation, commands, version in STEPS:
        print(f"\n{BOLD}{title}{RESET}")
        if explanation:
            print(f"{DIM}{explanation}{RESET}")
        for args in commands:
            run(args, version)
        if title.startswith("7."):
            show_latest_revision("default")
        if options.pause:
            input(f"{DIM}-- Enter to continue --{RESET}")

    print(f"\n{BOLD}Done.{RESET} Generated files: {HERE / 'migrations'}")


if __name__ == "__main__":
    main()
