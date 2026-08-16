"""The two gates.

Gate A and Gate B are frequently collapsed into a single "human in the loop"
control. They are not the same control and they fail in different ways.

Gate A - machine safety. Deterministic. Asks whether the output is safe to
emit at all. A Gate A failure means the system produced something it should
not hand to a downstream consumer, human or machine. Gate A can be fully
automated because every check it performs is decidable without knowing the
correct answer.

Gate B - human accountability. Asks who is answerable for the decision and
whether they must see it before it takes effect. Gate B is not a quality
check. A decision can be entirely correct and still require Gate B, because
accountability attaches to the consequence, not to the confidence.

Conflating them produces the common failure where a system escalates on low
confidence and auto-actions on high confidence, which means the most
consequential decisions receive the least human attention.
"""

from __future__ import annotations

import re

from .rubric import NOTIFICATION_SENSITIVE, is_consistent
from .schemas import Category, GateAResult, GateBResult, Severity, TriageDecision

# Gate A thresholds. A confidence at or below this floor indicates the model is
# effectively guessing, and a guess is not a safe artifact to emit.
CONFIDENCE_FLOOR = 0.30

# Patterns that should never appear in a rationale that will be written to an
# incident record. Free-text fields are the usual leak path.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_LONG_DIGITS = re.compile(r"\b\d{12,19}\b")
_INJECTION_MARKERS = re.compile(
    r"(ignore (all |the )?(previous|prior|above) instructions"
    r"|disregard (the )?(system|prior) prompt"
    r"|you are now"
    r"|<\s*/?\s*(system|instructions?)\s*>)",
    re.IGNORECASE,
)

# Gate B thresholds. Deliberately separate from the Gate A floor - they answer
# a different question and should be tunable independently.
REVIEW_CONFIDENCE_THRESHOLD = 0.70

_ACCOUNTABLE_ROLE: dict[Severity, str] = {
    Severity.SEV1: "Incident Commander",
    Severity.SEV2: "Service Owner",
    Severity.SEV3: "Duty Manager",
    Severity.SEV4: "Duty Manager",
}


def gate_a(decision: TriageDecision) -> GateAResult:
    """Machine safety gate. Deterministic, answer-agnostic checks."""
    violations: list[str] = []

    if not is_consistent(decision.impact, decision.urgency, decision.severity):
        violations.append(
            f"rubric_inconsistent: {decision.impact.value} + "
            f"{decision.urgency.value} does not derive {decision.severity.value}"
        )

    if decision.confidence <= CONFIDENCE_FLOOR:
        violations.append(
            f"confidence_below_floor: {decision.confidence:.2f} "
            f"<= {CONFIDENCE_FLOOR:.2f}"
        )

    if not decision.rationale.strip():
        violations.append("empty_rationale")

    if _EMAIL.search(decision.rationale):
        violations.append("pii_in_rationale: email address")

    if _LONG_DIGITS.search(decision.rationale):
        violations.append("pii_in_rationale: long numeric identifier")

    if _INJECTION_MARKERS.search(decision.rationale):
        violations.append("injection_marker_echoed_in_rationale")

    for indicator in decision.indicators:
        if _INJECTION_MARKERS.search(indicator):
            violations.append("injection_marker_echoed_in_indicators")
            break

    return GateAResult(passed=not violations, violations=violations)


def gate_b(decision: TriageDecision) -> GateBResult:
    """Human accountability gate.

    Triggers are additive and each names the reason a human is required. The
    reason matters as much as the outcome - an escalation with no stated
    trigger is not auditable.
    """
    triggers: list[str] = []

    if decision.severity in (Severity.SEV1, Severity.SEV2):
        triggers.append(f"consequence_threshold: {decision.severity.value}")

    if decision.category in (Category.SECURITY, Category.DATA_INTEGRITY):
        triggers.append(f"sensitive_category: {decision.category.value}")

    if decision.confidence < REVIEW_CONFIDENCE_THRESHOLD:
        triggers.append(
            f"low_confidence: {decision.confidence:.2f} "
            f"< {REVIEW_CONFIDENCE_THRESHOLD:.2f}"
        )

    if (
        decision.category.value in NOTIFICATION_SENSITIVE
        and decision.severity is Severity.SEV1
    ):
        triggers.append("notification_window_risk")

    role = _ACCOUNTABLE_ROLE[decision.severity]
    if decision.category in (Category.SECURITY, Category.DATA_INTEGRITY):
        role = f"{role} with CISO delegate"

    return GateBResult(
        human_review_required=bool(triggers),
        triggers=triggers,
        accountable_role=role,
    )
