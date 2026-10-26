"""``synalchemy.db``: the instance built from your config file, ready to import."""

from __future__ import annotations

import threading
from typing import Any

from synalchemy.core import SynAlchemy


class DefaultSynAlchemy:
    """Stands in for ``SynAlchemy.from_config()``, built the first time it's used.

    Importing it reads nothing, so it is safe at module level::

        from synalchemy import db

        async with db.session() as session:
            ...

    Every attribute is the real instance's. ``db.use(instance)`` swaps in your own
    (tests, or a config built in code); ``db.reset()`` forgets it, so the next use
    reads the config again.
    """

    _lock = threading.Lock()

    def __init__(self) -> None:
        self._instance: SynAlchemy | None = None

    @property
    def instance(self) -> SynAlchemy:
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = SynAlchemy.from_config()
        return self._instance

    def use(self, instance: SynAlchemy) -> SynAlchemy:
        """Make ``instance`` the default."""
        self._instance = instance
        return instance

    def reset(self) -> None:
        """Forget the current instance (dispose it first if it holds connections)."""
        self._instance = None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.instance, name)

    def __repr__(self) -> str:
        if self._instance is None:
            return "<synalchemy.db: not built yet>"
        return f"<synalchemy.db: {self._instance!r}>"


db = DefaultSynAlchemy()
