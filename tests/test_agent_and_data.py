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


class TestSelfImprovementGuardrails:
    """The loop's constraints are the product. Test them, not the loop."""

    def test_split_is_deterministic(self):
        from evals.selfimprove import stratified_split

        records = load_golden_set(GOLDEN_SET)
        a_dev, a_hold = stratified_split(records)
        b_dev, b_hold = stratified_split(records)
        assert [r.id for r in a_dev] == [r.id for r in b_dev]
        assert [r.id for r in a_hold] == [r.id for r in b_hold]

    def test_split_is_disjoint_and_complete(self):
        from evals.selfimprove import stratified_split

        records = load_golden_set(GOLDEN_SET)
        dev, hold = stratified_split(records)
        dev_ids, hold_ids = {r.id for r in dev}, {r.id for r in hold}
        assert not (dev_ids & hold_ids)
        assert dev_ids | hold_ids == {r.id for r in records}

    def test_split_preserves_class_balance(self):
        from evals.selfimprove import stratified_split

        records = load_golden_set(GOLDEN_SET)
        dev, hold = stratified_split(records)
        for severity in ("SEV1", "SEV2", "SEV3", "SEV4"):
            assert any(r.severity == severity for r in hold), (
                f"{severity} missing from holdout"
            )

    @pytest.mark.parametrize(
        "target",
        [
            "severity_matrix",
            "gate_a_thresholds",
            "gate_b_thresholds",
            "attempt_budget",
            "existing_label",
            "metric_definition",
        ],
    )
    def test_immutable_surfaces_are_blocked(self, target):
        from evals.selfimprove import GuardrailViolation, check_guardrails

        with pytest.raises(GuardrailViolation):
            check_guardrails({"target": target, "change": "x", "rationale": "y"})

    def test_unknown_target_is_blocked(self):
        from evals.selfimprove import GuardrailViolation, check_guardrails

        with pytest.raises(GuardrailViolation):
            check_guardrails({"target": "retrain_the_model"})

    def test_mutable_surfaces_pass(self):
        from evals.selfimprove import check_guardrails

        check_guardrails({"target": "prompt_guidance"})
        check_guardrails({"target": "new_eval_case"})

    def _report(self, under_rate, total=40):
        from metrics import EvalReport

        report = EvalReport(classifier="synthetic")
        report.total = total
        report.under_classified = round(under_rate * total)
        return report

    def test_small_gain_rejected_as_noise(self):
        from evals.selfimprove import evaluate_proposal

        verdict, _ = evaluate_proposal(
            self._report(0.30), self._report(0.30),
            self._report(0.29), self._report(0.29),
        )
        assert verdict == "rejected"

    def test_dev_gain_without_holdout_gain_halts(self):
        from evals.selfimprove import evaluate_proposal

        verdict, reason = evaluate_proposal(
            self._report(0.30), self._report(0.30),
            self._report(0.15), self._report(0.32),
        )
        assert verdict == "halt_overfit"
        assert "fitting the development split" in reason

    def test_balanced_gain_accepted(self):
        from evals.selfimprove import evaluate_proposal

        verdict, _ = evaluate_proposal(
            self._report(0.30), self._report(0.30),
            self._report(0.20), self._report(0.20),
        )
        assert verdict == "accepted"

    def test_lopsided_gain_accepted_with_warning(self):
        from evals.selfimprove import evaluate_proposal

        verdict, _ = evaluate_proposal(
            self._report(0.30), self._report(0.30),
            self._report(0.15), self._report(0.275),
        )
        assert verdict == "accepted_with_warning"


class TestOpenAICompatClassifier:
    """Contract and coercion tests. No network."""

    def test_known_providers_construct(self):
        from triage.classifiers.openai_compat import PROVIDERS, OpenAICompatClassifier

        for provider in PROVIDERS:
            c = OpenAICompatClassifier(provider=provider)
            assert c.name.startswith(provider)
            assert c.model

    def test_unknown_provider_rejected(self):
        from triage.classifiers.base import ClassifierError
        from triage.classifiers.openai_compat import OpenAICompatClassifier

        with pytest.raises(ClassifierError):
            OpenAICompatClassifier(provider="not-a-provider")

    def test_custom_base_url_bypasses_preset(self):
        from triage.classifiers.openai_compat import OpenAICompatClassifier

        c = OpenAICompatClassifier(
            provider="custom", model="m", base_url="http://example.test/v1"
        )
        assert c.model == "m"

    def test_satisfies_classifier_protocol(self):
        from triage.classifiers.base import Classifier
        from triage.classifiers.openai_compat import OpenAICompatClassifier

        assert isinstance(OpenAICompatClassifier(provider="ollama"), Classifier)

    def test_unreachable_endpoint_raises_classifier_error(self):
        from triage.classifiers.base import ClassifierError
        from triage.classifiers.openai_compat import OpenAICompatClassifier

        c = OpenAICompatClassifier(
            provider="custom", model="m", base_url="http://127.0.0.1:9/v1", timeout=1
        )
        with pytest.raises(ClassifierError):
            c.classify("T1", "payment gateway down")

    def test_classifier_error_is_caught_by_the_agent_loop(self):
        """An unreachable model must block, not crash the run."""
        from triage.classifiers.openai_compat import OpenAICompatClassifier
        from triage.schemas import OutcomeStatus

        c = OpenAICompatClassifier(
            provider="custom", model="m", base_url="http://127.0.0.1:9/v1", timeout=1
        )
        outcome = triage(c, "T1", "payment gateway down at all branches")
        assert outcome.status is OutcomeStatus.BLOCKED
        assert outcome.decision is None


class TestReasoningModelParsing:
    """Reasoning models wrap the answer. The parser must find it anyway."""

    GOOD = (
        '{"category":"availability","impact":"extensive","urgency":"critical",'
        '"confidence":0.9,"rationale":"All branches affected, no workaround."}'
    )

    def _ex(self, raw):
        from triage.classifiers.openai_compat import extract_decision_json

        return extract_decision_json(raw)

    def test_plain_json(self):
        assert self._ex(self.GOOD)["impact"] == "extensive"

    def test_think_block_with_braces_inside(self):
        raw = '<think>Consider {this} and {"impact":"minor"}.</think>\n' + self.GOOD
        assert self._ex(raw)["impact"] == "extensive"

    def test_markdown_fences(self):
        assert self._ex(f"```json\n{self.GOOD}\n```")["impact"] == "extensive"

    def test_prose_on_both_sides(self):
        raw = f"Here is my assessment:\n{self.GOOD}\nHope that helps."
        assert self._ex(raw)["impact"] == "extensive"

    def test_last_valid_object_wins(self):
        """A model that drafts then revises must be read at its final answer."""
        draft = self.GOOD.replace("extensive", "minor")
        raw = f"{draft}\nActually, on reflection:\n{self.GOOD}"
        assert self._ex(raw)["impact"] == "extensive"

    def test_unterminated_think_block(self):
        raw = "<thinking>truncated reasoning with {braces}\n" + self.GOOD
        assert self._ex(raw)["impact"] == "extensive"

    def test_object_without_required_keys_ignored(self):
        raw = '{"note":"thinking out loud"}\n' + self.GOOD
        assert self._ex(raw)["impact"] == "extensive"

    def test_no_decision_object_raises(self):
        from triage.classifiers.base import ClassifierError

        with pytest.raises(ClassifierError):
            self._ex("I cannot classify this incident.")


class TestCoverageFloor:
    """A classifier that refuses to answer must not pass the gate."""

    def _report(self, total, scored, under=0.0):
        from metrics import EvalReport

        report = EvalReport(classifier="synthetic")
        report.total = total
        report.scored = scored
        report.blocked = total - scored
        report.under_classified = round(under * total)
        report.within_one = scored
        report.exact = scored
        report.escalation_tp = scored
        return report

    def test_full_refusal_is_caught(self):
        from evals.run_evals import check_thresholds

        breaches = check_thresholds(self._report(60, 0))
        assert breaches
        assert any("coverage" in b for b in breaches)

    def test_partial_refusal_is_caught_despite_perfect_metrics(self):
        """The exploit: refuse most of the corpus, ace what remains."""
        from evals.run_evals import check_thresholds

        breaches = check_thresholds(self._report(60, 15, under=0.0))
        assert any("coverage" in b for b in breaches)

    def test_full_coverage_with_good_metrics_passes(self):
        from evals.run_evals import check_thresholds

        assert check_thresholds(self._report(60, 60, under=0.10)) == []


class TestPipelineInvariants:
    """Properties that must hold for every incident, regardless of accuracy."""

    def _outcomes(self):
        from triage.classifiers import BaselineClassifier

        c = BaselineClassifier()
        return [(r, triage(c, r.id, r.text)) for r in load_golden_set(GOLDEN_SET)]

    def test_severity_is_always_derived_from_the_axes(self):
        from triage.rubric import derive_severity

        for _, o in self._outcomes():
            if o.decision:
                assert (
                    derive_severity(o.decision.impact, o.decision.urgency)
                    is o.decision.severity
                )

    def test_consequential_severities_are_never_auto_emitted(self):
        from triage.schemas import OutcomeStatus, Severity

        for _, o in self._outcomes():
            if o.status is OutcomeStatus.EMITTED and o.decision:
                assert o.decision.severity not in (Severity.SEV1, Severity.SEV2)

    def test_gate_b_never_runs_after_a_gate_a_block(self):
        from triage.schemas import OutcomeStatus

        for _, o in self._outcomes():
            if o.status is OutcomeStatus.BLOCKED:
                assert o.gate_b is None

    def test_every_escalation_states_a_trigger(self):
        for _, o in self._outcomes():
            if o.gate_b and o.gate_b.human_review_required:
                assert o.gate_b.triggers

    def test_pipeline_is_deterministic(self):
        runs = [
            tuple(o.decision.severity.value for _, o in self._outcomes())
            for _ in range(3)
        ]
        assert len(set(runs)) == 1
