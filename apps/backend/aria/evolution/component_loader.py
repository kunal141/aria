"""
Component Loader — Week 28

Shared singleton update store and runtime loader for promoted component
versions.

Source of truth
---------------
The immutable versioned artifact file on disk (written by promote_canary /
rollback_update under ``deployments/<update_id><suffix>``) is the runtime
authority. ``load()`` reads from that file and re-verifies its SHA-256
against the active release's ``content_hash``. If the active release sets
``artifact_path`` but the file is missing, unreadable, outside the deployment
root, or hash-mismatched, ``load()`` FAILS CLOSED by raising
``ComponentArtifactError``. ``UpdateRelease.content`` is NEVER silently
substituted for an invalid on-disk artifact.

Modes
-----
- Active release with artifact_path → on-disk artifact is runtime data;
  ``UpdateRelease.content`` is proposal data (kept for diffing & rollback).
- Active release without artifact_path → ``UpdateRelease.content`` IS the
  runtime data (proposal-only / test mode; no deployment file).
- No active release → ``(default, None, None)``.

Consumers:
  - aria.nodes.evolution_node  — uses get_store() as the shared store
  - aria.skills.pr_review_skill — calls load("pr_review_prompt") to get
                                   the active prompt content and its hash
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from aria.evolution.update_manager.models import UpdateStatus, compute_hash
from aria.evolution.update_manager.store import InMemoryUpdateStore

_UPDATE_RELEASES_PATH = (
    Path(__file__).parent.parent.parent / "update_releases.jsonl"
)

# Module-level singleton — shared between evolution_node and skill nodes.
_store = InMemoryUpdateStore(persist_path=_UPDATE_RELEASES_PATH)


class ComponentArtifactError(RuntimeError):
    """
    Raised when an active release's on-disk artifact cannot be trusted —
    missing, unreadable, outside the deployment root, or hash-mismatched.
    Callers must NOT fall back to UpdateRelease.content; this is fail-closed
    by design.
    """


def get_store() -> InMemoryUpdateStore:
    """Return the shared update store singleton."""
    return _store


def load(
    component_name: str,
    *,
    default: str = "",
) -> tuple[str, Optional[str], Optional[str]]:
    """
    Return ``(content, content_hash, semantic_version)`` for the most recently
    activated version of ``component_name``.

    When the active release has ``artifact_path`` set, the disk artifact is
    the runtime authority. This function reads the artifact, confines its
    path under the deployment root, and verifies its SHA-256 matches
    ``content_hash``. Any failure raises ``ComponentArtifactError`` — the
    in-memory ``content`` field is NEVER silently substituted.

    When no ``artifact_path`` is set on the active release, the in-memory
    ``content`` field IS the runtime data (proposal-only / test mode).

    Falls back to ``(default, None, None)`` only when there is no active
    release for the component.
    """
    actives = [
        u for u in _store.list_by_component(component_name)
        if u.status == UpdateStatus.active
    ]
    if not actives:
        return default, None, None
    best = max(actives, key=lambda u: u.active_at or "")

    if best.artifact_path:
        # Lazy import to avoid circular dependency at module load.
        from aria.evolution.update_manager.operations import _confined_path

        try:
            confined = _confined_path(best.artifact_path)
        except ValueError as exc:
            raise ComponentArtifactError(
                f"component_loader: active release for {component_name!r} "
                f"(update_id={best.update_id!r}, version={best.semantic_version!r}) "
                f"has artifact_path outside deployment root: {exc}"
            ) from exc

        try:
            on_disk = confined.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            # OSError covers missing file / permission denied / I/O failure.
            # UnicodeError (includes UnicodeDecodeError) covers binary
            # corruption — bytes on disk are not valid UTF-8. Both fail
            # closed through the documented typed exception; the in-memory
            # ``content`` field is never substituted.
            raise ComponentArtifactError(
                f"component_loader: active release for {component_name!r} "
                f"(update_id={best.update_id!r}, version={best.semantic_version!r}) "
                f"artifact at {confined} is missing, unreadable, or corrupted: {exc}"
            ) from exc

        if compute_hash(on_disk) != best.content_hash:
            raise ComponentArtifactError(
                f"component_loader: active release for {component_name!r} "
                f"(update_id={best.update_id!r}, version={best.semantic_version!r}) "
                f"artifact at {confined} fails hash verification "
                f"(expected {best.content_hash!r})."
            )

        return on_disk, best.content_hash, best.semantic_version

    # No artifact_path — content field IS runtime data (proposal-only mode).
    if not best.content:
        return default, None, None
    return best.content, best.content_hash, best.semantic_version
