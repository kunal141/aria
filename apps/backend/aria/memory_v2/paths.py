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


def goals_db_path() -> Path:
    """Absolute path to the SQLite goal/roadmap/task store (V3.1).

    ``${ARIA_DATA_DIR}/goals/store.sqlite`` — same confined, gitignored runtime
    pattern as the memory and workspace stores. Never inside the source package.
    """
    return aria_data_dir() / "goals" / "store.sqlite"


def skills_db_path() -> Path:
    """Absolute path to the SQLite skill-evolution store (V3.5).

    ``${ARIA_DATA_DIR}/skills/store.sqlite`` — same confined, gitignored runtime
    pattern as the memory / workspace / goal stores. Never inside the source package.
    """
    return aria_data_dir() / "skills" / "store.sqlite"


def awareness_db_path() -> Path:
    """Absolute path to the SQLite work-memory + world-awareness store (V3.6).

    ``${ARIA_DATA_DIR}/awareness/store.sqlite`` — same confined, gitignored runtime
    pattern as the other stores. Never inside the source package.
    """
    return aria_data_dir() / "awareness" / "store.sqlite"


def collaboration_db_path() -> Path:
    """Absolute path to the SQLite team-collaboration store (V3.7).

    ``${ARIA_DATA_DIR}/collaboration/store.sqlite`` — same confined, gitignored
    runtime pattern as the other stores. Never inside the source package. Holds
    DRAFT-ONLY communication artifacts; nothing here is ever sent externally.
    """
    return aria_data_dir() / "collaboration" / "store.sqlite"


def routines_db_path() -> Path:
    """Absolute path to the SQLite scheduled-routines store (V3.8).

    ``${ARIA_DATA_DIR}/routines/store.sqlite`` — same confined, gitignored runtime
    pattern as the other stores. Never inside the source package. Holds LOCAL,
    deterministic routine definitions/runs/outputs; nothing here browses the live
    web, runs a daemon, or performs any external action.
    """
    return aria_data_dir() / "routines" / "store.sqlite"


def actions_db_path() -> Path:
    """Absolute path to the SQLite controlled-live-execution store (V3.9).

    ``${ARIA_DATA_DIR}/actions/store.sqlite`` — same confined, gitignored runtime
    pattern as the other stores. Never inside the source package. Holds action
    intents / approvals / receipts for the governed action gate; live execution is
    blocked by default and nothing here performs a real external write.
    """
    return aria_data_dir() / "actions" / "store.sqlite"


def dashboard_db_path() -> Path:
    """Absolute path to the SQLite manager-dashboard store (V3.10).

    ``${ARIA_DATA_DIR}/dashboard/store.sqlite`` — same confined, gitignored runtime
    pattern as the other stores. Never inside the source package. Holds READ-ONLY
    aggregated snapshots / ROI / approval-queue / risk / proof records; nothing here
    executes work, approves anything, or performs an external action.
    """
    return aria_data_dir() / "dashboard" / "store.sqlite"


def runtime_adapters_db_path() -> Path:
    """Absolute path to the SQLite runtime-adapter store (V4.1).

    ``${ARIA_DATA_DIR}/runtime_adapters/store.sqlite`` — same confined, gitignored
    runtime pattern as the other stores. Never inside the source package. Holds adapter
    definitions / capabilities / requests / receipts for the governed adapter layer;
    only the internal_mock adapter executes (dry-run / mock), and nothing here performs
    a real external runtime, model, network, or credential call.
    """
    return aria_data_dir() / "runtime_adapters" / "store.sqlite"


def model_routing_db_path() -> Path:
    """Absolute path to the SQLite model-routing store (V4.2).

    ``${ARIA_DATA_DIR}/model_routing/store.sqlite`` — same confined, gitignored
    runtime pattern as the other stores. Never inside the source package. Holds model
    provider registry / capability-cost-risk profiles / fallback + sovereignty policies /
    route requests / route decisions for the governed model-routing layer. Every route is
    a DECISION only — nothing here executes a model, calls a provider, uses a network, or
    touches a credential.
    """
    return aria_data_dir() / "model_routing" / "store.sqlite"


def employee_runs_db_path() -> Path:
    """Confined SQLite store for integrated virtual-employee runs.

    The final orchestration layer persists correlations, attempts, evaluations, repair
    plans and manager outcomes under ``${ARIA_DATA_DIR}/employee_runs/store.sqlite``.
    It never stores runtime data inside the importable source package.
    """
    return aria_data_dir() / "employee_runs" / "store.sqlite"


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
