from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_schemas_rubric import make_decision
from triage.agent import triage
from triage.classifiers.base import ClassifierError
from triage.harness import load_golden_set
from triage.rubric import derive_severity
from triage.schemas import Category, Impact, OutcomeStatus, Severity, Urgency

GOLDEN_SET = Path(__file__).resolve().parent.parent / "evals/data/golden_set.jsonl"


class StubClassifier:
    """Returns a scripted sequence of decisions, one per attempt."""

    name = "stub"

    def __init__(self, decisions):
        self._decisions = list(decisions)
        self.calls = 0
        self.feedback_seen = []

    def classify(self, incident_id, text, feedback=None):
        self.calls += 1
        self.feedback_seen.append(feedback)
        item = self._decisions[min(self.calls - 1, len(self._decisions) - 1)]
        if isinstance(item, Exception):
            raise item
        return item


class TestAgentLoop:
    def test_clean_pass_emits_or_escalates_in_one_attempt(self):
        stub = StubClassifier([make_decision()])
        outcome = triage(stub, "INC-1", "text")
        assert stub.calls == 1
        assert outcome.status is OutcomeStatus.ESCALATED  # SEV1

    def test_auto_emit_when_no_trigger(self):
        decision = make_decision(
            category=Category.PERFORMANCE,
            impact=Impact.MINOR,
            urgency=Urgency.LOW,
            severity=Severity.SEV4,
            confidence=0.95,
        )
        outcome = triage(StubClassifier([decision]), "INC-2", "text")
        assert outcome.status is OutcomeStatus.EMITTED

    def test_gate_a_failure_triggers_one_retry(self):
        bad = make_decision(confidence=0.05)
        good = make_decision()
        stub = StubClassifier([bad, good])
        outcome = triage(stub, "INC-3", "text")
        assert stub.calls == 2
        assert outcome.gate_a.passed
        assert stub.feedback_seen[1] is not None
        assert "confidence_below_floor" in stub.feedback_seen[1]

    def test_persistent_failure_blocks(self):
        bad = make_decision(confidence=0.05)
        stub = StubClassifier([bad, bad])
        outcome = triage(stub, "INC-4", "text")
        assert outcome.status is OutcomeStatus.BLOCKED
        assert outcome.gate_b is None
        assert outcome.decision is not None  # preserved for the human reviewer

    def test_attempt_budget_is_respected(self):
        bad = make_decision(confidence=0.05)
        stub = StubClassifier([bad] * 10)
        triage(stub, "INC-5", "text", max_attempts=2)
        assert stub.calls == 2

    def test_classifier_error_blocks_without_gate_b(self):
        stub = StubClassifier([ClassifierError("bad json")])
        outcome = triage(stub, "INC-6", "text")
        assert outcome.status is OutcomeStatus.BLOCKED
        assert outcome.decision is None
        assert any("classifier_error" in v for v in outcome.gate_a.violations)

    def test_trace_records_every_phase(self):
        outcome = triage(StubClassifier([make_decision()]), "INC-7", "text")
        phases = {step.phase for step in outcome.trace}
        assert {"reason", "act", "observe"} <= phases

    def test_reflection_never_leaks_gate_b(self):
        """Gate B triggers must not reach the classifier as feedback."""
        bad = make_decision(confidence=0.05)
        stub = StubClassifier([bad, make_decision()])
        triage(stub, "INC-8", "text")
        for feedback in stub.feedback_seen:
            if feedback:
                assert "accountable" not in feedback.lower()
                assert "human" not in feedback.lower()


@pytest.fixture(scope="module")
def records():
    return load_golden_set(GOLDEN_SET)


class TestGoldenSet:
    def test_set_is_non_trivial(self, records):
        assert len(records) >= 50

    def test_ids_are_unique(self, records):
        ids = [r.id for r in records]
        assert len(ids) == len(set(ids))

    def test_every_label_matches_the_rubric(self, records):
        for r in records:
            expected = derive_severity(Impact(r.impact), Urgency(r.urgency))
            assert expected.value == r.severity, f"{r.id} label contradicts the rubric"

    def test_expected_review_matches_gate_b_policy(self, records):
        for r in records:
            policy = r.severity in ("SEV1", "SEV2") or r.category in (
                "security",
                "data_integrity",
            )
            assert policy == r.expects_human_review, f"{r.id} review label is wrong"

    def test_all_severities_represented(self, records):
        assert {r.severity for r in records} == {"SEV1", "SEV2", "SEV3", "SEV4"}

    def test_no_class_dominates(self, records):
        for severity in ("SEV1", "SEV2", "SEV3", "SEV4"):
            share = sum(r.severity == severity for r in records) / len(records)
            assert share < 0.5, f"{severity} dominates the set"


class TestBaselineRegression:
    """Pins the baseline's known profile.

    The baseline is a reference floor and is not expected to pass the
    governance thresholds. This test guards against silent regression, not
    against underperformance.
    """

    def test_baseline_holds_its_recorded_floor(self):
        from evals.run_evals import evaluate

        report = evaluate("baseline")
        assert report.exact_accuracy >= 0.55
        assert report.within_one_accuracy >= 0.90
        assert report.escalation_recall >= 0.88
        assert report.blocked == 0

    def test_baseline_still_fails_the_governance_gate(self):
        """Documents the finding rather than hiding it."""
        from evals.run_evals import check_thresholds, evaluate

        breaches = check_thresholds(evaluate("baseline"))
        assert breaches, "if the baseline now passes, revisit whether an LLM is needed"
