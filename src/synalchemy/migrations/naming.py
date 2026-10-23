"""Revision ids, file names and the revision file template."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
REVISION_RE = re.compile(r"^(?P<ts>\d{8}T\d{6}Z)_[0-9a-f]{4}$")


def timestamp_of(revision: str) -> datetime | None:
    match = REVISION_RE.match(revision)
    if match is None:
        return None
    return datetime.strptime(match["ts"], TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)


def new_revision_id(after: str | None = None, now: datetime | None = None) -> str:
    """Return ``<UTC timestamp>_<4 hex>``, always later than ``after``.

    The random suffix keeps ids unique when two people generate in the same second.
    """
    now = (now or datetime.now(timezone.utc)).replace(microsecond=0)
    previous = timestamp_of(after) if after else None
    if previous is not None and now <= previous:
        now = previous + timedelta(seconds=1)
    return f"{now.strftime(TIMESTAMP_FORMAT)}_{secrets.token_hex(2)}"


def slugify(message: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_")
    return slug[:max_length].rstrip("_")


def revision_filename(revision: str, message: str) -> str:
    slug = slugify(message)
    return f"{revision}_{slug}.py" if slug else f"{revision}.py"


_TEMPLATE = '''\
"""{message}

Revision: {revision}
Revises:  {revises}
Database: {db_name}
Created:  {created}
"""

from __future__ import annotations

import sqlalchemy as sa
{imports}
revision = {revision!r}
down_revision = {down_revision!r}
db_name = {db_name!r}


{def_kw} upgrade() -> None:
    {upgrades}


{def_kw} downgrade() -> None:
    {downgrades}
'''


def render_revision(
    *,
    revision: str,
    down_revision: str | None,
    db_name: str,
    message: str,
    upgrades: str = "pass",
    downgrades: str = "pass",
    imports: str = "",
    use_async: bool = False,
) -> str:
    helpers = (
        "from synalchemy.migrations import aop, get_connection  # noqa: F401"
        if use_async
        else "from synalchemy.migrations import op, run_async  # noqa: F401"
    )
    import_lines = "\n".join(line for line in (imports, helpers) if line)
    safe_message = (message.strip() or "empty revision").replace("\\", "\\\\").replace('"', '\\"')
    created = timestamp_of(revision)
    return _TEMPLATE.format(
        message=safe_message,
        revision=revision,
        revises=down_revision or "<base>",
        down_revision=down_revision,
        db_name=db_name,
        created=created.isoformat() if created else "",
        imports=import_lines + "\n",
        def_kw="async def" if use_async else "def",
        upgrades=upgrades,
        downgrades=downgrades,
    )


def write_revision(directory: Path, *, revision: str, message: str, **kwargs: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / revision_filename(revision, message)
    path.write_text(
        render_revision(revision=revision, message=message, **kwargs),  # type: ignore[arg-type]
        encoding="utf-8",
    )
    return path
