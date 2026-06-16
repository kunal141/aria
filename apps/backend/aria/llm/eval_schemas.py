"""
Frozen, minimal, *evaluation-only* JSON schemas for the Week 31 model-fitness
gate (V2 plan §6.3, finding P1.2).

Why these exist
---------------
The Week 31 fitness gate must check that the configured local model can emit the
*shapes* V2 will depend on (a routing decision and a memory-extraction record)
**without** pulling Week 32's full orchestrator / memory implementation forward.

These two models are therefore **compatibility contracts**, not implementations:

  - They are deliberately MINIMAL — only the fields the fitness gate asserts on.
  - They are NOT the full ``OrchestratorDecision`` / ``DomainMemoryProposal``
    models. Those are designed and built in Week 32 and **must remain
    backward-compatible** with these frozen shapes (Week 32 may ADD fields; it
    must not rename or drop these).
  - They are evaluation-only: nothing in the runtime conversation or memory path
    consumes them. They exist so the fitness gate has a stable thing to validate.

Keep these frozen. Changing a field here is a contract change that Week 32 code
depends on.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The four orchestrator decision actions (V2 plan §7) and the three domain-memory
# operations (V2 plan §8). These value sets ARE the contract: the fitness gate
# must prove the model emits one of these, not an arbitrary string. Week 32's
# full models may add fields but must keep these exact value sets.
RoutingAction = Literal["converse", "run_workflow", "propose_memory", "clarify"]
MemoryOperation = Literal["create", "update", "delete"]


class MinimalRoutingDecision(BaseModel):
    """Frozen eval-only shape of a routing decision.

    Week 32's full ``OrchestratorDecision`` (action ∈ {converse, run_workflow,
    propose_memory, clarify}, plus rationale/payload/confidence/correlation_id)
    must stay backward-compatible with this: ``action`` + ``rationale`` are the
    two fields the fitness gate asserts the model can produce, and ``action`` is
    constrained to the four valid actions so the gate proves a *valid* decision —
    an arbitrary string like ``"delete_everything"`` is rejected.
    """

    model_config = ConfigDict(extra="ignore")  # forward-compat: Week 32 may add fields

    action: RoutingAction
    rationale: str = Field(min_length=1)


class MinimalMemoryExtraction(BaseModel):
    """Frozen eval-only shape of a domain-memory extraction.

    Week 32's full ``DomainMemoryProposal`` (operation, structured_value,
    source_turn_id, owner, scope, confidence, status, ...) must stay
    backward-compatible with this: ``operation`` + ``structured_value`` are the
    two fields the fitness gate asserts the model can produce, and ``operation``
    is constrained to the planned memory operations so the gate proves a *valid*
    extraction — an arbitrary string like ``"exfiltrate"`` is rejected.
    """

    model_config = ConfigDict(extra="ignore")  # forward-compat: Week 32 may add fields

    operation: MemoryOperation
    structured_value: str = Field(min_length=1)
