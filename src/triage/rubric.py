"""Severity rubric.

Derived entirely from public standards. See docs/rubric_provenance.md for the
anchoring and for the reasons this file contains no organisation-specific
thresholds, taxonomies or escalation paths.

The matrix below is the single source of truth for severity. A classifier that
returns a severity inconsistent with its own stated impact and urgency has
produced an internally incoherent output, and Gate A rejects it on that basis
alone - without needing to know the correct answer.
"""

from __future__ import annotations

from .schemas import Impact, Severity, Urgency

# ITIL-style impact/urgency priority matrix.
SEVERITY_MATRIX: dict[tuple[Impact, Urgency], Severity] = {
    (Impact.EXTENSIVE, Urgency.CRITICAL): Severity.SEV1,
    (Impact.EXTENSIVE, Urgency.HIGH): Severity.SEV1,
    (Impact.EXTENSIVE, Urgency.MEDIUM): Severity.SEV2,
    (Impact.EXTENSIVE, Urgency.LOW): Severity.SEV3,
    (Impact.SIGNIFICANT, Urgency.CRITICAL): Severity.SEV1,
    (Impact.SIGNIFICANT, Urgency.HIGH): Severity.SEV2,
    (Impact.SIGNIFICANT, Urgency.MEDIUM): Severity.SEV2,
    (Impact.SIGNIFICANT, Urgency.LOW): Severity.SEV3,
    (Impact.MODERATE, Urgency.CRITICAL): Severity.SEV2,
    (Impact.MODERATE, Urgency.HIGH): Severity.SEV3,
    (Impact.MODERATE, Urgency.MEDIUM): Severity.SEV3,
    (Impact.MODERATE, Urgency.LOW): Severity.SEV4,
    (Impact.MINOR, Urgency.CRITICAL): Severity.SEV3,
    (Impact.MINOR, Urgency.HIGH): Severity.SEV3,
    (Impact.MINOR, Urgency.MEDIUM): Severity.SEV4,
    (Impact.MINOR, Urgency.LOW): Severity.SEV4,
}

IMPACT_DEFINITIONS: dict[Impact, str] = {
    Impact.EXTENSIVE: (
        "Enterprise-wide or customer-wide effect. A whole business service, "
        "region, or customer channel is affected."
    ),
    Impact.SIGNIFICANT: (
        "A large but bounded population - multiple departments, sites, or a "
        "substantial share of a single critical service."
    ),
    Impact.MODERATE: (
        "A contained group - one team, one site, or one non-critical service."
    ),
    Impact.MINOR: (
        "One user or a cosmetic defect with no service effect."
    ),
}

URGENCY_DEFINITIONS: dict[Urgency, str] = {
    Urgency.CRITICAL: (
        "Business function is stopped now, or the effect compounds materially "
        "with every minute of delay. No viable workaround."
    ),
    Urgency.HIGH: (
        "Business function is degraded and deteriorating. Workaround is partial "
        "or costly to sustain."
    ),
    Urgency.MEDIUM: (
        "Business function continues on a workaround that can be held for the "
        "remainder of the working day."
    ),
    Urgency.LOW: (
        "No time pressure. Can be scheduled into normal work."
    ),
}

SEVERITY_DEFINITIONS: dict[Severity, str] = {
    Severity.SEV1: "Critical. Command structure stands up immediately.",
    Severity.SEV2: "Major. Service owner leads, senior management informed.",
    Severity.SEV3: "Moderate. Normal support process, tracked to resolution.",
    Severity.SEV4: "Low. Scheduled into standard work queue.",
}

# Categories where mis-classification carries asymmetric consequence, because a
# missed call may forfeit a regulatory notification window. Used by Gate B, not
# by severity derivation.
NOTIFICATION_SENSITIVE = frozenset({"security", "data_integrity", "availability"})


def derive_severity(impact: Impact, urgency: Urgency) -> Severity:
    """Return the rubric-mandated severity for an impact/urgency pair."""
    return SEVERITY_MATRIX[(impact, urgency)]


def is_consistent(impact: Impact, urgency: Urgency, severity: Severity) -> bool:
    """True when the stated severity matches what the rubric mandates."""
    return derive_severity(impact, urgency) is severity


def rubric_as_prompt_block() -> str:
    """Render the rubric as text for inclusion in a model prompt.

    The rubric lives in one place. The prompt reads from it rather than
    restating it, so the prompt and the Gate A consistency check can never
    drift apart.
    """
    lines = ["IMPACT LEVELS"]
    lines += [f"- {k.value}: {v}" for k, v in IMPACT_DEFINITIONS.items()]
    lines.append("")
    lines.append("URGENCY LEVELS")
    lines += [f"- {k.value}: {v}" for k, v in URGENCY_DEFINITIONS.items()]
    lines.append("")
    lines.append("SEVERITY IS DERIVED FROM IMPACT x URGENCY")
    for (impact, urgency), severity in SEVERITY_MATRIX.items():
        lines.append(f"- {impact.value} + {urgency.value} -> {severity.value}")
    return "\n".join(lines)
