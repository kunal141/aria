"""
Model Lifecycle Registry v1 — offline demo.

Runs the full governed lifecycle (register → evaluate → request_approval →
approve → activate → register v2 → activate v2 [supersede v1] → rollback to v1)
inside an isolated temporary directory, prints the registry state and the typed
Work Ledger v2 lifecycle events it emitted, and exits.

PROTOTYPE ONLY. No network, no LLM, no GPU, no model download, no deployment.
The demo's last line of output explicitly states the prototype boundary.

Usage
-----

    cd apps/backend
    uv run python -m aria.model_registry.demo
    uv run python -m aria.model_registry.demo --keep   # retain tmp dir
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from aria.ledger.reader import LedgerReader
from aria.ledger.writer import LedgerWriter
from aria.model_registry import (
    InMemoryModelStore,
    ModelProvider,
    ModelRecord,
    ModelRegistry,
    ModelType,
    OfflineEvaluator,
    default_pr_review_holdout,
    utc_now,
)


def _write_mock_artifact(artifact_root: Path, name: str, content: str) -> tuple[str, str]:
    """Write a tiny deterministic mock artifact; return (path, sha256-of-bytes)."""
    artifact_root.mkdir(parents=True, exist_ok=True)
    path = artifact_root / name
    path.write_text(content, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return str(path), digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Model Lifecycle Registry v1 demo")
    parser.add_argument("--tmp", type=Path, default=None, help="Directory to use (default: tempdir).")
    parser.add_argument("--keep", action="store_true", help="Keep the demo directory after exit.")
    args = parser.parse_args(argv)

    workdir = args.tmp if args.tmp is not None else Path(tempfile.mkdtemp(prefix="aria_registry_demo_"))
    workdir.mkdir(parents=True, exist_ok=True)
    artifact_root = workdir / "artifacts"
    store_path = workdir / "registry.jsonl"
    ledger_path = workdir / "ledger_v2.jsonl"

    consumer = "pr_review_skill"
    writer = LedgerWriter(ledger_path)
    registry = ModelRegistry(
        store=InMemoryModelStore(persist_path=store_path),
        known_consumers={consumer},
        authorized_approvers={"human:kunal"},
        artifact_root=artifact_root,
        writer=writer,
        clock=utc_now,
    )
    evaluator = OfflineEvaluator()
    holdout = default_pr_review_holdout()

    # ── v1.0.0: a deterministic mock fine-tune candidate ───────────────────────
    v1_path, v1_hash = _write_mock_artifact(
        artifact_root, "pr_review-1.0.0.bin", "MOCK-ADAPTER-WEIGHTS-v1"
    )
    v1 = ModelRecord(
        model_id="pr_review-ft-1_0_0",
        model_name="pr_review_specialist",
        semantic_version="1.0.0",
        provider=ModelProvider.prototype,
        model_type=ModelType.fine_tuned,
        base_model="Qwen2.5-Coder-7B-Instruct",
        artifact_path=v1_path,
        artifact_hash=v1_hash,
        dataset_id="ds-pr-review-2026w24",
        dataset_hash="a" * 64,
        created_by="aria",
        created_at=utc_now(),
        production_consumer=consumer,
    )
    registry.register_model(v1)
    registry.record_evaluation(v1.model_id, evaluator.evaluate(v1, holdout))
    registry.request_approval(v1.model_id)
    registry.approve_model(v1.model_id, approver="human:kunal")
    registry.activate_model(v1.model_id)
    print(f"[v1] registered, evaluated, approved, ACTIVE  ({v1.model_id})")

    # ── v2.0.0: supersedes v1 on activation ────────────────────────────────────
    v2_path, v2_hash = _write_mock_artifact(
        artifact_root, "pr_review-2.0.0.bin", "MOCK-ADAPTER-WEIGHTS-v2"
    )
    v2 = ModelRecord(
        model_id="pr_review-ft-2_0_0",
        model_name="pr_review_specialist",
        semantic_version="2.0.0",
        provider=ModelProvider.prototype,
        model_type=ModelType.fine_tuned,
        base_model="Qwen2.5-Coder-7B-Instruct",
        artifact_path=v2_path,
        artifact_hash=v2_hash,
        dataset_id="ds-pr-review-2026w26",
        dataset_hash="b" * 64,
        created_by="aria",
        created_at=utc_now(),
        production_consumer=consumer,
    )
    registry.register_model(v2)
    registry.record_evaluation(v2.model_id, evaluator.evaluate(v2, holdout))
    registry.request_approval(v2.model_id)
    registry.approve_model(v2.model_id, approver="human:kunal")
    registry.activate_model(v2.model_id)
    active = registry.get_active_model(consumer)
    print(f"[v2] ACTIVE; v1 superseded -> deprecated. Active is now {active.semantic_version}")

    # ── Rollback to v1 ─────────────────────────────────────────────────────────
    registry.rollback_model(consumer, v1.model_id)
    active = registry.get_active_model(consumer)
    print(f"[rollback] restored {active.semantic_version} as ACTIVE; v2 rolled_back")

    # ── Summary ────────────────────────────────────────────────────────────────
    print("\n-- Registry versions ------------------------------------------")
    for r in registry.list_versions(consumer):
        print(f"  {r.semantic_version:8s}  {r.status.value:12s}  {r.model_id}")

    cmp = registry.compare_versions(v1.model_id, v2.model_id)
    print("\n-- Version comparison (v1 -> v2) -------------------------------")
    print(json.dumps(cmp.model_dump(), indent=2, sort_keys=True, default=str))

    lifecycle_events = [
        e for e in LedgerReader(v2_path=ledger_path).v2_events()
        if e.event_type.value == "model_lifecycle"
    ]
    print(f"\n-- Work Ledger v2: {len(lifecycle_events)} model_lifecycle events emitted --")
    for e in lifecycle_events:
        print(f"  {e.model_version:8s}  {str(e.from_status):16s} -> {e.to_status}")

    if not args.keep:
        shutil.rmtree(workdir, ignore_errors=True)
        print("\n(demo directory removed; pass --keep to retain it)")
    else:
        print(f"\n(demo directory retained at {workdir})")

    print()
    print("Prototype only. No real model training or deployment was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
