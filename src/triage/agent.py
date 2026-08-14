"""The reason-act-observe-reflect loop.

The loop is bounded and the bound is a governance property, not a cost
control. An agent permitted to retry indefinitely against a validator will
eventually satisfy the validator, and what it has satisfied is the validator
rather than the requirement. Two attempts, then the decision goes to a human
with its violations attached.

Reflection is fed only Gate A violations, never Gate B triggers. Telling the
model that a human is about to review its answer changes the answer, and not
for the better.
"""

from __future__ import annotations

from .classifiers.base import Classifier, ClassifierError
from .gates import gate_a, gate_b
from .schemas import (
    GateAResult,
    OutcomeStatus,
    TraceStep,
    TriageDecision,
    TriageOutcome,
)

MAX_ATTEMPTS = 2


def triage(
    classifier: Classifier,
    incident_id: str,
    text: str,
    max_attempts: int = MAX_ATTEMPTS,
) -> TriageOutcome:
    """Run one incident through the full governed pipeline."""
    trace: list[TraceStep] = []
    feedback: str | None = None
    decision: TriageDecision | None = None
    result: GateAResult = GateAResult(passed=False, violations=["not_attempted"])

    for attempt in range(1, max_attempts + 1):
        trace.append(
            TraceStep(
                attempt=attempt,
                phase="reason",
                detail=(
                    "retry with gate feedback" if feedback else "initial assessment"
                ),
            )
        )

        try:
            decision = classifier.classify(incident_id, text, feedback)
        except ClassifierError as exc:
            trace.append(
                TraceStep(attempt=attempt, phase="act", detail=f"classifier error: {exc}")
            )
            result = GateAResult(passed=False, violations=[f"classifier_error: {exc}"])
            decision = None
            break

        trace.append(
            TraceStep(
                attempt=attempt,
                phase="act",
                detail=(
                    f"{decision.severity.value} / {decision.category.value} "
                    f"@ confidence {decision.confidence:.2f}"
                ),
            )
        )

        result = gate_a(decision)
        trace.append(
            TraceStep(
                attempt=attempt,
                phase="observe",
                detail=(
                    "gate A passed"
                    if result.passed
                    else "gate A violations: " + "; ".join(result.violations)
                ),
            )
        )

        if result.passed:
            break

        if attempt < max_attempts:
            feedback = "\n".join(f"- {v}" for v in result.violations)
            trace.append(
                TraceStep(
                    attempt=attempt,
                    phase="reflect",
                    detail="violations returned to classifier for correction",
                )
            )
        else:
            trace.append(
                TraceStep(
                    attempt=attempt,
                    phase="reflect",
                    detail="attempt budget exhausted, routing to human with violations",
                )
            )

    if decision is None or not result.passed:
        return TriageOutcome(
            incident_id=incident_id,
            status=OutcomeStatus.BLOCKED,
            decision=decision,
            gate_a=result,
            gate_b=None,
            trace=trace,
        )

    b_result = gate_b(decision)
    trace.append(
        TraceStep(
            attempt=len({s.attempt for s in trace}),
            phase="gate_b",
            detail=(
                f"human review required, accountable: {b_result.accountable_role}"
                if b_result.human_review_required
                else "no accountability trigger, safe to auto-emit"
            ),
        )
    )

    return TriageOutcome(
        incident_id=incident_id,
        status=(
            OutcomeStatus.ESCALATED
            if b_result.human_review_required
            else OutcomeStatus.EMITTED
        ),
        decision=decision,
        gate_a=result,
        gate_b=b_result,
        trace=trace,
    )
