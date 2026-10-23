"""Loading revision files and checking they form one linear chain per database."""

from __future__ import annotations

import ast
import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from synalchemy.exceptions import ChainError

UP, DOWN = "up", "down"
_HEADER_NAMES = {"revision", "down_revision", "db_name"}
_DOWN_LINE_RE = re.compile(r"^down_revision(\s*:[^=\n]+)?\s*=.*$", re.M)
_REVISES_LINE_RE = re.compile(r"^Revises:.*$", re.M)


@dataclass(eq=False)
class Revision:
    id: str
    down: str | None
    db_name: str | None
    message: str
    path: Path
    _module: ModuleType | None = field(default=None, repr=False)

    @classmethod
    def from_file(cls, path: Path) -> Revision | None:
        """Read the header constants without importing the file. ``None`` if it isn't one."""
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        values: dict[str, Any] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in _HEADER_NAMES:
                    try:
                        values[target.id] = ast.literal_eval(value)
                    except ValueError as exc:
                        raise ChainError(f"{path}: {target.id} must be a literal.") from exc
        if "revision" not in values:
            return None
        down = values.get("down_revision")
        if down is not None and not isinstance(down, str):
            raise ChainError(f"{path}: down_revision must be a single revision id or None.")
        doc = (ast.get_docstring(tree) or "").strip()
        return cls(
            id=values["revision"],
            down=down,
            db_name=values.get("db_name"),
            message=doc.splitlines()[0] if doc else "",
            path=path,
        )

    def load(self) -> ModuleType:
        if self._module is None:
            safe = re.sub(r"\W", "_", f"{self.db_name}_{self.id}")
            spec = importlib.util.spec_from_file_location(f"synalchemy_revision_{safe}", self.path)
            if spec is None or spec.loader is None:  # pragma: no cover
                raise ChainError(f"Can't import {self.path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self._module = module
        return self._module

    def function(self, direction: str) -> Callable[[], Any]:
        name = "upgrade" if direction == UP else "downgrade"
        fn = getattr(self.load(), name, None)
        if fn is None:
            raise ChainError(f"{self.path} has no {name}() function.")
        return fn

    def rewrite_down(self, new_down: str | None) -> None:
        text = self.path.read_text("utf-8")
        text = _DOWN_LINE_RE.sub(
            lambda m: f"down_revision{m.group(1) or ''} = {new_down!r}", text, count=1
        )
        text = _REVISES_LINE_RE.sub(f"Revises:  {new_down or '<base>'}", text, count=1)
        self.path.write_text(text, encoding="utf-8")
        self.down = new_down
        self._module = None


class Chain:
    """All revisions of one database, ordered from base to head."""

    def __init__(self, db_name: str, directory: Path, revisions: list[Revision]) -> None:
        self.db_name = db_name
        self.directory = directory
        self.revisions: dict[str, Revision] = {}
        self.problems: list[str] = []
        self.warnings: list[str] = []
        for rev in revisions:
            if rev.id in self.revisions:
                self.problems.append(
                    f"revision {rev.id} is defined twice "
                    f"({self.revisions[rev.id].path.name}, {rev.path.name})"
                )
            else:
                self.revisions[rev.id] = rev
        self.ordered: list[Revision] = self._order()

    @classmethod
    def load(cls, db_name: str, directory: Path) -> Chain:
        revisions = []
        if directory.is_dir():
            for path in sorted(directory.glob("*.py")):
                if path.name.startswith(("_", ".")):
                    continue
                rev = Revision.from_file(path)
                if rev is not None:
                    revisions.append(rev)
        return cls(db_name, directory, revisions)

    # -- structure -----------------------------------------------------------

    def _order(self) -> list[Revision]:
        revs = self.revisions
        children: dict[str | None, list[Revision]] = {}
        for rev in revs.values():
            if rev.db_name is not None and rev.db_name != self.db_name:
                self.problems.append(
                    f"{rev.path.name} declares db_name={rev.db_name!r} but lives in the "
                    f"{self.db_name!r} folder"
                )
            if rev.down is not None and rev.down not in revs:
                self.problems.append(f"{rev.id} revises {rev.down}, which doesn't exist")
            children.setdefault(rev.down, []).append(rev)

        for parent, kids in children.items():
            if len(kids) > 1:
                names = ", ".join(sorted(k.id for k in kids))
                where = "the base" if parent is None else parent
                self.problems.append(f"{where} has several children: {names}")
        if self.problems:
            return []

        ordered: list[Revision] = []
        current = children.get(None, [None])[0]
        while current is not None:
            ordered.append(current)
            if current.id < (current.down or ""):
                self.warnings.append(f"{current.id} is older than its parent {current.down}")
            current = next(iter(children.get(current.id, [])), None)
        if len(ordered) != len(revs):
            self.problems.append("revisions form a cycle or aren't connected to the base")
            return []
        return ordered

    def validate(self) -> None:
        if self.problems:
            details = "\n  - ".join(self.problems)
            raise ChainError(
                f"Migration chain for {self.db_name!r} is broken:\n  - {details}\n"
                "Run `migrations rechain` to re-link unapplied revisions in timestamp order."
            )

    @property
    def head(self) -> str | None:
        self.validate()
        return self.ordered[-1].id if self.ordered else None

    def index(self, revision: str | None) -> int:
        """Position in the chain; -1 for the base (``None``)."""
        self.validate()
        if revision is None:
            return -1
        for i, rev in enumerate(self.ordered):
            if rev.id == revision:
                return i
        raise ChainError(
            f"Database {self.db_name!r} is at revision {revision}, which isn't in "
            f"{self.directory}. Was a revision file deleted?"
        )

    def resolve(self, ref: str | None) -> str | None:
        """Turn ``head``, ``base``, a full id or a unique id prefix into a revision id."""
        if ref is None or ref == "base":
            return None
        if ref == "head":
            return self.head
        if ref in self.revisions:
            return ref
        matches = [rid for rid in self.revisions if rid.startswith(ref)]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise ChainError(f"No revision {ref!r} in database {self.db_name!r}.")
        raise ChainError(f"Revision prefix {ref!r} is ambiguous: {', '.join(sorted(matches))}.")

    def steps(self, current: str | None, target: str | None) -> list[tuple[Revision, str]]:
        """Revisions to run, with their direction, to move from ``current`` to ``target``."""
        start, end = self.index(current), self.index(target)
        if end > start:
            return [(self.ordered[i], UP) for i in range(start + 1, end + 1)]
        return [(self.ordered[i], DOWN) for i in range(start, end, -1)]

    def target_down(self, current: str | None, count: int) -> str | None:
        position = self.index(current)
        if count < 1:
            raise ChainError("Steps must be at least 1.")
        if count > position + 1:
            raise ChainError(
                f"Database {self.db_name!r} has only {position + 1} applied revision(s); "
                f"can't go down {count}."
            )
        new_position = position - count
        return self.ordered[new_position].id if new_position >= 0 else None

    # -- repair --------------------------------------------------------------

    def rechain(
        self, applied_head: str | None, *, dry_run: bool = False
    ) -> list[tuple[Revision, str | None, str | None]]:
        """Re-link unapplied revisions in timestamp order after ``applied_head``.

        Applied revisions are never touched. Returns ``(revision, old_down, new_down)``.
        """
        applied: set[str] = set()
        current = applied_head
        while current is not None:
            if current in applied:
                raise ChainError(f"Cycle detected at {current}.")
            rev = self.revisions.get(current)
            if rev is None:
                raise ChainError(
                    f"Applied revision {current} has no file in {self.directory}; can't rechain."
                )
            applied.add(current)
            current = rev.down

        changes: list[tuple[Revision, str | None, str | None]] = []
        previous = applied_head
        for rev in sorted(self.revisions.values(), key=lambda r: r.id):
            if rev.id in applied:
                continue
            if rev.down != previous:
                changes.append((rev, rev.down, previous))
                if not dry_run:
                    rev.rewrite_down(previous)
            previous = rev.id
        return changes
