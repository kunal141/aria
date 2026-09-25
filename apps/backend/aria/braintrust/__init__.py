"""Local Claude/Codex strategy and isolated build-review consoles."""

from aria.braintrust.build_review import BuildReviewManager
from aria.braintrust.runner import BraintrustManager

__all__ = ["BraintrustManager", "BuildReviewManager"]
