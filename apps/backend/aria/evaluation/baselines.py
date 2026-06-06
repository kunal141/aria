"""
Eval Baselines — Week 14

Stores the last-known-good score for every skill × golden example.
On each regression run, the runner compares live scores to baselines
and flags any dimension that dropped by more than REGRESSION_THRESHOLD.

File format (eval_baselines.json):
{
  "pr_review::0": {"overall": 3.8, "dimensions": {"issue_specificity": 4, ...}},
  "kpi::2":       {"overall": 3.2, "dimensions": {"hypothesis_quality": 3, ...}}
}

Key = "{skill_name}::{golden_index}" — deterministic, no UUIDs needed.

Update rule:
  - baselines.update() only writes if new score >= current baseline
    (prevents a bad run from lowering the bar)
  - baselines.promote() forces an update (used when you deliberately
    accept a lower score because the rubric changed)
"""
import json
import os
from typing import Optional


_BASELINE_FILE = os.environ.get("ARIA_BASELINES_PATH") or os.path.join(os.path.dirname(__file__), "eval_baselines.json")

REGRESSION_THRESHOLD = 0.5   # score must drop by this much to count as regression


# ── Public API ────────────────────────────────────────────────────────────────

def get(skill_name: str, golden_index: int) -> Optional[dict]:
    """
    Return stored baseline for skill × example, or None if not yet set.
    Returns: {"overall": float, "dimensions": dict[str, int]}
    """
    key   = _key(skill_name, golden_index)
    store = _load()
    return store.get(key)


def update(skill_name: str, golden_index: int, overall: float, dimensions: dict[str, int]) -> bool:
    """
    Write baseline only if overall >= current baseline (never lower the bar).
    Returns True if the baseline was updated, False if skipped.
    """
    existing = get(skill_name, golden_index)
    if existing and overall < existing["overall"]:
        return False
    _write(skill_name, golden_index, overall, dimensions)
    return True


def promote(skill_name: str, golden_index: int, overall: float, dimensions: dict[str, int]) -> None:
    """Force-write baseline regardless of current value. Use when rubric changes."""
    _write(skill_name, golden_index, overall, dimensions)


def is_regression(
    skill_name: str,
    golden_index: int,
    new_overall: float,
) -> bool:
    """Return True if new_overall is more than REGRESSION_THRESHOLD below baseline."""
    baseline = get(skill_name, golden_index)
    if baseline is None:
        return False
    return (baseline["overall"] - new_overall) > REGRESSION_THRESHOLD


def list_baselines() -> dict:
    """Return all stored baselines (for display)."""
    return _load()


# ── Internal ──────────────────────────────────────────────────────────────────

def _key(skill_name: str, golden_index: int) -> str:
    return f"{skill_name}::{golden_index}"


def _load() -> dict:
    if not os.path.exists(_BASELINE_FILE):
        return {}
    try:
        with open(_BASELINE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _write(skill_name: str, golden_index: int, overall: float, dimensions: dict[str, int]) -> None:
    store    = _load()
    key      = _key(skill_name, golden_index)
    store[key] = {"overall": round(overall, 2), "dimensions": dimensions}
    with open(_BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)
