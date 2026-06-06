"""
LATS — Language Agent Tree Search — Week 24.

A lightweight, deterministic implementation of the LATS algorithm
(Zhou et al., 2023) applied to ARIA's decision-making layer.

Each node represents a candidate DecisionOption.
Tree search selects the option with the best UCT score after N iterations,
using the composite scorer as the evaluation function (no LLM required).

When an LLM is available (future), the expansion step can generate new
candidate options from the current best node — enabling multi-hop reasoning.
For V1, options are provided upfront; LATS acts as a principled ranker.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from aria.decision.models import DecisionOption
from aria.decision.scorer import score_option


# ── LATS Node ─────────────────────────────────────────────────────────────────

@dataclass
class LATSNode:
    option:   DecisionOption
    parent:   Optional[LATSNode] = field(default=None, repr=False)
    children: List[LATSNode]     = field(default_factory=list)
    visits:   int                = 0
    value:    float              = 0.0   # cumulative reward

    def uct_score(self, exploration_weight: float = 1.414) -> float:
        """
        Upper Confidence Bound for Trees.
        Balances exploitation (value / visits) vs exploration (sqrt(log N / n)).
        Unvisited nodes always selected first (returns +inf).
        """
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent else self.visits
        exploitation = self.value / self.visits
        exploration  = exploration_weight * math.sqrt(
            math.log(max(parent_visits, 1)) / self.visits
        )
        return exploitation + exploration

    def update(self, reward: float) -> None:
        """Backpropagate reward to this node and all ancestors."""
        node: Optional[LATSNode] = self
        while node is not None:
            node.visits += 1
            node.value  += reward
            node = node.parent

    @property
    def mean_value(self) -> float:
        return self.value / self.visits if self.visits > 0 else 0.0


# ── LATS Tree ─────────────────────────────────────────────────────────────────

class LATSTree:
    """
    A flat LATS tree rooted at a virtual root node.
    All option nodes are direct children of the root — V1 supports single-level
    search; multi-level expansion (with LLM) is a V2 extension.
    """

    def __init__(
        self,
        options: List[DecisionOption],
        evaluator: Callable[[DecisionOption], float] = score_option,
        exploration_weight: float = 1.414,
    ) -> None:
        if not options:
            raise ValueError("LATSTree requires at least one DecisionOption.")
        self._evaluator        = evaluator
        self._exploration      = exploration_weight
        self._root             = LATSNode(option=options[0])  # virtual root (unused)
        self._nodes: List[LATSNode] = [
            LATSNode(option=opt, parent=self._root) for opt in options
        ]
        self._root.children = self._nodes
        self._iterations       = 0

    def _select(self) -> LATSNode:
        """Pick the child with the highest UCT score."""
        return max(
            self._nodes,
            key=lambda n: n.uct_score(self._exploration),
        )

    def step(self) -> LATSNode:
        """Run one LATS iteration: select → evaluate → backpropagate."""
        node   = self._select()
        reward = self._evaluator(node.option)
        node.update(reward)
        self._iterations += 1
        return node

    def run(self, max_iterations: int = 10) -> DecisionOption:
        """Run up to max_iterations steps, then return the best option."""
        for _ in range(max_iterations):
            self.step()
        return self.best_option

    @property
    def best_option(self) -> DecisionOption:
        """Return the option with highest mean value after all iterations."""
        best = max(self._nodes, key=lambda n: n.mean_value)
        return best.option

    @property
    def iterations(self) -> int:
        return self._iterations


# ── Public helper ──────────────────────────────────────────────────────────────

def run_lats(
    options: List[DecisionOption],
    *,
    evaluator: Callable[[DecisionOption], float] = score_option,
    max_iterations: int = 10,
    exploration_weight: float = 1.414,
) -> tuple[DecisionOption, int]:
    """
    Run LATS over a list of DecisionOptions.

    Returns:
        (best_option, iterations_run)
    """
    tree = LATSTree(
        options=options,
        evaluator=evaluator,
        exploration_weight=exploration_weight,
    )
    best = tree.run(max_iterations=max_iterations)
    return best, tree.iterations
