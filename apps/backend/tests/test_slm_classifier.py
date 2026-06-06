"""
Deterministic tests for the SLM Classifier — Week 25 (Pillar 24).
No LLM, no network. All tests run fully in isolation.
"""
import pytest

from aria.slm.classifier import SLMClassifier, ClassificationResult, slm_classifier


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_slm(task_type: str):
    """Return an SLM callable that always returns the given task_type."""
    return lambda text: task_type


# ── ClassificationResult ──────────────────────────────────────────────────────

def test_classification_result_fields():
    r = ClassificationResult(task_type="kpi", confidence=0.85, method="keyword", reason="KPI keyword")
    assert r.task_type  == "kpi"
    assert r.confidence == pytest.approx(0.85)
    assert r.method     == "keyword"


def test_classification_result_is_confident_true():
    r = ClassificationResult(task_type="kpi", confidence=0.85, method="keyword", reason="r")
    assert r.is_confident is True


def test_classification_result_is_confident_false():
    r = ClassificationResult(task_type="general", confidence=0.5, method="keyword", reason="r")
    assert r.is_confident is False


def test_classification_result_is_confident_boundary():
    r = ClassificationResult(task_type="kpi", confidence=0.6, method="keyword", reason="r")
    assert r.is_confident is True


def test_classification_result_serialises():
    r = ClassificationResult(task_type="pr_review", confidence=0.9, method="slm", reason="slm hit")
    d = r.model_dump()
    assert "task_type" in d
    assert "method"    in d


# ── SLMClassifier — keyword path (default) ────────────────────────────────────

def test_keyword_path_returns_classification_result():
    clf = SLMClassifier()
    r   = clf.classify("CTR dropped 18% on feed this week")
    assert isinstance(r, ClassificationResult)


def test_keyword_path_method_is_keyword():
    clf = SLMClassifier()
    r   = clf.classify("CTR dropped 18%")
    assert r.method == "keyword"


def test_keyword_path_pr_review():
    clf = SLMClassifier()
    r   = clf.classify("Review my pull request for the recommendation engine")
    assert r.task_type == "pr_review"


def test_keyword_path_kpi():
    clf = SLMClassifier()
    r   = clf.classify("Metric anomaly detected on notification CTR")
    assert r.task_type == "kpi"


def test_keyword_path_ci_cd():
    clf = SLMClassifier()
    r   = clf.classify("Build failed on the notification service pipeline")
    assert r.task_type == "ci_cd"


def test_keyword_path_general_fallback():
    clf = SLMClassifier()
    r   = clf.classify("What's the weather today?")
    assert r.task_type == "general"
    assert r.confidence == pytest.approx(0.60)


def test_keyword_path_has_nonempty_reason():
    clf = SLMClassifier()
    r   = clf.classify("Review my PR")
    assert len(r.reason) > 0


# ── SLMClassifier — SLM path (mock SLM) ──────────────────────────────────────

def test_slm_path_returns_slm_method():
    clf = SLMClassifier(slm_fn=_mock_slm("kpi"))
    r   = clf.classify("anything")
    assert r.method == "slm"


def test_slm_path_valid_task_type_accepted():
    for tt in ["pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "analytics_qa", "general"]:
        clf = SLMClassifier(slm_fn=_mock_slm(tt))
        r   = clf.classify("some text")
        assert r.task_type == tt
        assert r.method    == "slm"


def test_slm_path_returns_confidence():
    clf = SLMClassifier(slm_fn=_mock_slm("kpi"))
    r   = clf.classify("any")
    assert 0.0 <= r.confidence <= 1.0


# ── P2.7: SLM must reject invalid task types ─────────────────────────────────

def test_slm_invalid_task_type_falls_back_to_keyword():
    """SLM returning an unsupported task type must trigger keyword fallback."""
    clf = SLMClassifier(slm_fn=_mock_slm("delete_everything"))
    r   = clf.classify("CTR dropped 18%")
    # Must NOT accept the invalid type
    assert r.task_type != "delete_everything"


def test_slm_invalid_task_type_uses_keyword_method():
    clf = SLMClassifier(slm_fn=_mock_slm("unknown_action"))
    r   = clf.classify("CTR dropped")
    assert r.method == "keyword"


def test_slm_invalid_task_type_reason_mentions_fallback():
    clf = SLMClassifier(slm_fn=_mock_slm("hack_the_planet"))
    r   = clf.classify("CTR dropped")
    assert "fell back to keyword" in r.reason.lower() or "keyword" in r.reason.lower()


def test_slm_invalid_task_type_produces_valid_classification():
    """After fallback, result must be a real supported task type."""
    clf = SLMClassifier(slm_fn=_mock_slm("FORBIDDEN"))
    r   = clf.classify("Review my pull request")
    valid = {"pr_review", "kpi", "ci_cd", "jira", "qa", "test_review", "analytics_qa", "general", "unknown"}
    assert r.task_type in valid


def test_slm_empty_string_task_type_falls_back():
    clf = SLMClassifier(slm_fn=_mock_slm(""))
    r   = clf.classify("Build failed on pipeline")
    assert r.task_type != ""


def test_slm_exception_falls_back_to_keyword():
    def bad_slm(text: str) -> str:
        raise RuntimeError("SLM service unavailable")

    clf = SLMClassifier(slm_fn=bad_slm)
    r   = clf.classify("Build failed on pipeline")
    assert r.method    == "keyword"
    assert r.task_type == "ci_cd"


def test_slm_exception_reason_mentions_fallback():
    def bad_slm(text: str) -> str:
        raise RuntimeError("timeout")

    clf = SLMClassifier(slm_fn=bad_slm)
    r   = clf.classify("Review PR")
    assert "fell back to keyword" in r.reason.lower()


# ── Module singleton ──────────────────────────────────────────────────────────

def test_module_singleton_exists():
    assert slm_classifier is not None
    assert isinstance(slm_classifier, SLMClassifier)


def test_module_singleton_uses_keyword_backend():
    r = slm_classifier.classify("CTR dropped this week")
    assert r.method == "keyword"
