"""
Work Ledger v0 — Week 4

Logs every task as a single JSON line to work_ledger.jsonl.
This is the seed of Pillar 16 (AI Work Ledger).

By Week 29, this file will have 25 weeks of entries and feed
the ROI dashboard: "ARIA completed 847 tasks, saving ~340 hours."

Week 4:  task_id, task_type, routing_reason, timestamp
Week 8:  + artifact_id (what ARIA produced)
Week 13: + langsmith_trace_id (link every task to its trace)
Week 15: + approval_id (governance actions)
Week 22: + outcome (was the task useful? accepted/rejected?)
Week 27: + error, platform_evidence (drive EvolutionMonitor signal detection)
Week 29: full ROI dashboard built from all accumulated entries
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

LEDGER_FILE = Path(__file__).parent.parent / "work_ledger.jsonl"


def log_task(
    task_id: str,
    task_type: str,
    routing_reason: str,
    *,
    error: Optional[str] = None,
    platform_evidence: Optional[str] = None,
) -> None:
    """
    Append one task record to the work ledger.

    error            : error message if the task failed; None on success.
    platform_evidence: JSON-serialized EvidencedAnswer (from state.platform_evidence);
                       used by EvolutionMonitor to detect low support rates.
    """
    entry: dict = {
        "task_id":          task_id,
        "task_type":        task_type,
        "routing_reason":   routing_reason,
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "error":            error,
        "platform_evidence": platform_evidence,
        "week":             4,
    }
    with open(LEDGER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_ledger() -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    with open(LEDGER_FILE, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
