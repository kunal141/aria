"""
Evolvable Component Registry — Week 28 / Round 11

The single source of truth for which components ARIA may evolve. An
``EvolutionProposal`` whose ``target_component`` is not registered here is
rejected at model validation time; the ``ProposalPipeline`` re-checks at
release-creation time as a second defence layer.

Each registration declares:
  - ``name``                : logical component name (matches the
                              ``component_name`` field on every
                              ``UpdateRelease`` for this component, and the
                              ``component_name`` argument to
                              ``component_loader.load``).
  - ``component_type``      : taxonomy bucket used to type the
                              ``UpdateRelease.component_type`` field.
  - ``artifact_subdir``     : subdirectory under the module-level
                              ``DEPLOYMENT_ROOT`` where the production
                              artifact for this component lives.
  - ``artifact_extension``  : file extension for the artifact (e.g. ``.txt``).
  - ``production_consumer`` : dotted-path of the module that calls
                              ``component_loader.load(name)`` at runtime.
                              Recorded so a reviewer can audit "what code
                              actually reads this artifact in prod?"
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from aria.evolution.update_manager.models import ComponentType


@dataclass(frozen=True)
class ComponentRegistration:
    name:                str
    component_type:      ComponentType
    artifact_subdir:     str
    artifact_extension:  str
    production_consumer: str


class UnknownComponentError(ValueError):
    """Raised when a proposal targets a component not in the evolvable registry."""


# Registry of evolvable components.  Adding to this list is the ONLY way to
# make a component a valid ``target_component`` for an ``EvolutionProposal``.
# Production consumers are documented for audit; the registry is authoritative
# for what ARIA may rewrite in production.
_REGISTRY: dict[str, ComponentRegistration] = {
    "pr_review_prompt": ComponentRegistration(
        name="pr_review_prompt",
        component_type=ComponentType.prompt,
        artifact_subdir="prompts",
        artifact_extension=".txt",
        production_consumer="aria.skills.pr_review_skill",
    ),
}


def get_registration(name: str) -> ComponentRegistration:
    """Look up a registration. Raises UnknownComponentError if not registered."""
    reg = _REGISTRY.get(name)
    if reg is None:
        raise UnknownComponentError(
            f"Component {name!r} is not in the evolvable registry. "
            f"Known evolvable components: {sorted(_REGISTRY.keys())}"
        )
    return reg


def is_evolvable(name: str) -> bool:
    return name in _REGISTRY


def list_evolvable_components() -> list[ComponentRegistration]:
    return list(_REGISTRY.values())


def artifact_path_for(name: str, deployment_root: Path) -> str:
    """
    Build the deterministic deployment artifact path for ``name`` under
    ``deployment_root``. The path is constructed but NOT confined here — the
    operations module and component_loader run confinement at write/read time
    as part of the defence-in-depth chain.
    """
    reg = get_registration(name)
    return str(deployment_root / reg.artifact_subdir / f"{name}{reg.artifact_extension}")
