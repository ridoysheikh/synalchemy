from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from synalchemy import ChainError
from synalchemy.migrations import naming
from synalchemy.migrations.chain import DOWN, UP, Chain


def write(directory: Path, rev: str, down: str | None, db: str = "default") -> None:
    naming.write_revision(
        directory, revision=rev, message=f"rev {rev}", down_revision=down, db_name=db
    )


R1, R2, R3 = "20260101T000000Z_aaaa", "20260102T000000Z_bbbb", "20260103T000000Z_cccc"


def test_revision_ids_sort_and_never_go_backwards() -> None:
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rev = naming.new_revision_id(now=now)
    assert naming.REVISION_RE.match(rev)
    assert rev.startswith("20260101T000000Z_")
    later = naming.new_revision_id(after="20270101T000000Z_ffff", now=now)
    assert later.startswith("20270101T000001Z_")
    assert naming.revision_filename(rev, "Add users!") == f"{rev}_add_users.py"


def test_linear_chain(tmp_path: Path) -> None:
    write(tmp_path, R1, None)
    write(tmp_path, R2, R1)
    write(tmp_path, R3, R2)
    chain = Chain.load("default", tmp_path)
    chain.validate()
    assert [r.id for r in chain.ordered] == [R1, R2, R3]
    assert chain.head == R3
    assert chain.resolve("20260102") == R2
    assert chain.resolve("base") is None
    assert [(r.id, d) for r, d in chain.steps(None, R2)] == [(R1, UP), (R2, UP)]
    assert [(r.id, d) for r, d in chain.steps(R3, R1)] == [(R3, DOWN), (R2, DOWN)]
    assert chain.target_down(R3, 3) is None
    with pytest.raises(ChainError, match="only 3 applied"):
        chain.target_down(R3, 4)
    with pytest.raises(ChainError, match="ambiguous"):
        chain.resolve("2026")


def test_branch_is_detected_and_rechained(tmp_path: Path) -> None:
    write(tmp_path, R1, None)
    write(tmp_path, R3, R1)  # two developers both branched from R1
    write(tmp_path, R2, R1)
    chain = Chain.load("default", tmp_path)
    with pytest.raises(ChainError, match="several children"):
        chain.validate()

    changes = chain.rechain(R1, dry_run=True)
    assert [(r.id, old, new) for r, old, new in changes] == [(R3, R1, R2)]

    chain.rechain(R1)
    fixed = Chain.load("default", tmp_path)
    assert [r.id for r in fixed.ordered] == [R1, R2, R3]
    text = next(tmp_path.glob(f"{R3}*.py")).read_text()
    assert f"down_revision = {R2!r}" in text
    assert f"Revises:  {R2}" in text


def test_missing_parent_and_wrong_folder(tmp_path: Path) -> None:
    write(tmp_path, R2, R1)
    write(tmp_path, R3, R2, db="analytics")
    chain = Chain.load("default", tmp_path)
    problems = "\n".join(chain.problems)
    assert "doesn't exist" in problems
    assert "declares db_name='analytics'" in problems


def test_unknown_current_revision(tmp_path: Path) -> None:
    write(tmp_path, R1, None)
    with pytest.raises(ChainError, match="isn't in"):
        Chain.load("default", tmp_path).index("20990101T000000Z_dead")
