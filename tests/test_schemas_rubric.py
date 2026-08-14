from __future__ import annotations

import pytest
from pydantic import ValidationError

from triage.rubric import (
    IMPACT_DEFINITIONS,
    SEVERITY_MATRIX,
    URGENCY_DEFINITIONS,
    derive_severity,
    is_consistent,
    rubric_as_prompt_block,
)
from triage.schemas import Category, Impact, Severity, TriageDecision, Urgency


def make_decision(**overrides) -> TriageDecision:
    payload = {
        "incident_id": "INC-TEST",
        "category": Category.AVAILABILITY,
        "impact": Impact.EXTENSIVE,
        "urgency": Urgency.CRITICAL,
        "severity": Severity.SEV1,
        "confidence": 0.9,
        "rationale": "A sufficiently long rationale for validation purposes.",
        "indicators": ["outage"],
    }
    payload.update(overrides)
    return TriageDecision(**payload)


class TestSchemas:
    def test_valid_decision_constructs(self):
        assert make_decision().severity is Severity.SEV1

    def test_decision_is_immutable(self):
        decision = make_decision()
        with pytest.raises(ValidationError):
            decision.confidence = 0.1

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            make_decision(unexpected_field="value")

    @pytest.mark.parametrize("bad", [-0.01, 1.01, 5.0])
    def test_confidence_bounds_enforced(self, bad):
        with pytest.raises(ValidationError):
            make_decision(confidence=bad)

    def test_short_rationale_rejected(self):
        with pytest.raises(ValidationError):
            make_decision(rationale="too short")

    def test_unknown_enum_value_rejected(self):
        with pytest.raises(ValidationError):
            make_decision(severity="SEV5")

    def test_severity_rank_orders_correctly(self):
        assert Severity.SEV1.rank < Severity.SEV4.rank


class TestRubric:
    def test_matrix_is_total(self):
        assert len(SEVERITY_MATRIX) == len(Impact) * len(Urgency)
        for impact in Impact:
            for urgency in Urgency:
                assert (impact, urgency) in SEVERITY_MATRIX

    def test_every_level_is_defined(self):
        assert set(IMPACT_DEFINITIONS) == set(Impact)
        assert set(URGENCY_DEFINITIONS) == set(Urgency)

    def test_derivation_is_monotonic_in_urgency(self):
        """Holding impact fixed, raising urgency never lowers severity."""
        order = [Urgency.LOW, Urgency.MEDIUM, Urgency.HIGH, Urgency.CRITICAL]
        for impact in Impact:
            ranks = [derive_severity(impact, u).rank for u in order]
            assert ranks == sorted(ranks, reverse=True)

    def test_derivation_is_monotonic_in_impact(self):
        order = [Impact.MINOR, Impact.MODERATE, Impact.SIGNIFICANT, Impact.EXTENSIVE]
        for urgency in Urgency:
            ranks = [derive_severity(i, urgency).rank for i in order]
            assert ranks == sorted(ranks, reverse=True)

    def test_consistency_check(self):
        assert is_consistent(Impact.EXTENSIVE, Urgency.CRITICAL, Severity.SEV1)
        assert not is_consistent(Impact.EXTENSIVE, Urgency.CRITICAL, Severity.SEV4)

    def test_prompt_block_covers_all_levels(self):
        block = rubric_as_prompt_block()
        for level in list(Impact) + list(Urgency) + list(Severity):
            assert level.value in block
