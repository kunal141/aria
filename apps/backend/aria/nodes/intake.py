import uuid
from aria.state import ARIAState


# Keywords that suggest the task touches sensitive internal data
_CONFIDENTIAL_SIGNALS = frozenset([
    "salary", "payroll", "hr ", "aadhaar", "pan ", "password",
    "secret", "credential", "private key", "employee",
])
_RESTRICTED_SIGNALS = frozenset([
    "production db", "production database", "prod database", "root access", "sudo",
    "aws key", "gcp key", "azure key",
])


def _infer_sensitivity(raw_input: str) -> str:
    text = raw_input.lower()
    if any(sig in text for sig in _RESTRICTED_SIGNALS):
        return "restricted"
    if any(sig in text for sig in _CONFIDENTIAL_SIGNALS):
        return "confidential"
    # Engineering tasks (PR review, KPI, CI/CD, Jira) are internal by default
    return "internal"


def intake(state: ARIAState) -> dict:
    """
    First node every task passes through.
    Assigns task_id, infers data_sensitivity, opens the audit trail.
    """
    task_id     = str(uuid.uuid4())
    sensitivity = state.get("data_sensitivity") or _infer_sensitivity(state.get("raw_input", ""))

    # Log the sensitivity assignment to the audit trail
    try:
        from aria.security.audit_log import log_sensitivity_assignment
        source = "explicit" if state.get("data_sensitivity") else "inferred"
        log_sensitivity_assignment(task_id, sensitivity, source)
    except Exception:
        pass   # security logging must never break task execution

    return {
        "task_id":          task_id,
        "task_status":      "routing",
        "steps_completed":  ["intake"],
        "data_sensitivity": sensitivity,
    }
