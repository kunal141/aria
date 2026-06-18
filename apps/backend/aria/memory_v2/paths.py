"""
Runtime data paths for V2 (Week 32).

All V2 runtime data (the SQLite domain-memory store now; workspaces in Week 33)
lives under ``ARIA_DATA_DIR`` — a gitignored runtime directory that is **never**
inside the importable ``aria`` source package.

Resolution:
  - ``ARIA_DATA_DIR`` env var, if set (tests redirect this to ``tmp_path``).
  - else ``apps/backend/.aria_data`` — a sibling of the ``aria`` package, not
    inside it, and gitignored.

Path confinement: callers must only ever derive paths *under* ``aria_data_dir()``
via the helpers here, so runtime files can never escape the confined tree.
Nothing here creates directories or files at import time — creation happens lazily
at write time inside the store.
"""
from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_DIRNAME = ".aria_data"


def _backend_root() -> Path:
    """``apps/backend`` — the directory that holds the ``aria`` package.

    This file is ``apps/backend/aria/memory_v2/paths.py`` → ``parents[2]`` is
    ``apps/backend``. The default data dir is a sibling of ``aria/``, never inside
    the source package.
    """
    return Path(__file__).resolve().parents[2]


def aria_data_dir() -> Path:
    """The confined runtime data root. Honours ``ARIA_DATA_DIR`` (tests set it)."""
    env = os.getenv("ARIA_DATA_DIR")
    if env and env.strip():
        return Path(env)
    return _backend_root() / _DEFAULT_DIRNAME


def memory_db_path() -> Path:
    """Absolute path to the SQLite domain-memory store (``…/memory/store.sqlite``)."""
    return aria_data_dir() / "memory" / "store.sqlite"


def workspaces_dir() -> Path:
    """Confined root for persistent workspaces (``${ARIA_DATA_DIR}/workspaces``)."""
    return aria_data_dir() / "workspaces"


def workspaces_db_path() -> Path:
    """Absolute path to the SQLite workspace-metadata store."""
    return workspaces_dir() / "workspaces.sqlite"


def workspace_artifact_dir(workspace_id: str) -> Path:
    """Confined per-workspace runtime directory for artifact bytes."""
    return workspaces_dir() / workspace_id


def is_confined(path: Path) -> bool:
    """True iff ``path`` resolves inside ``aria_data_dir()`` (path-confinement guard).

    Resolves both sides first, so ``..`` traversal and symlink escapes are caught.
    """
    try:
        Path(path).resolve().relative_to(aria_data_dir().resolve())
        return True
    except ValueError:
        return False


class PathConfinementError(ValueError):
    """A runtime path escaped the confined ``ARIA_DATA_DIR`` tree."""

    def __init__(self, path: Path, root: Path) -> None:
        super().__init__(
            f"Refusing path {str(path)!r}: it resolves outside the confined runtime "
            f"data root {str(root)!r} (ARIA_DATA_DIR). Set ARIA_DATA_DIR to the intended "
            f"root and place data under it."
        )
        self.path = path
        self.root = root


def ensure_confined(path: Path | str) -> Path:
    """Return ``path`` as a ``Path`` if it is confined under ``aria_data_dir()``,
    else raise :class:`PathConfinementError`. Enforces, not just reports."""
    p = Path(path)
    if not is_confined(p):
        raise PathConfinementError(p, aria_data_dir())
    return p
