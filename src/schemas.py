"""Output contracts for the triage pipeline.

These models validate the *shape* of a classification, not its *correctness*.
That distinction is deliberate and is the subject of docs/design.md. A
schema-valid decision can still be wrong, and a wrong decision can still be
schema-valid. Severity correctness is assessed by the rubric consistency check
in Gate A and measured against ground truth by the eval suite.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """Incident severity levels, derived from the impact/urgency matrix."""

    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"

    @property
    def rank(self) -> int:
        """Lower number means more severe. Used for ordering comparisons."""
        return int(self.value[-1])


class Impact(str, Enum):
    """Breadth of business effect. Anchored on ITIL 4 incident management."""

    EXTENSIVE = "extensive"
    SIGNIFICANT = "significant"
    MODERATE = "moderate"
    MINOR = "minor"


class Urgency(str, Enum):
    """Speed at which the effect becomes intolerable to the business."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Category(str, Enum):
    """Incident category. Kept deliberately small and generic."""

    AVAILABILITY = "availability"
    SECURITY = "security"
    DATA_INTEGRITY = "data_integrity"
    PERFORMANCE = "performance"
    THIRD_PARTY = "third_party"
    CAPACITY = "capacity"
    CHANGE = "change"


class TriageDecision(BaseModel):
    """A single classification produced by a classifier.

    This is the only structure a classifier is permitted to emit. Anything a
    model returns that does not parse into this shape is a Gate A failure, not
    a low-quality answer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    incident_id: str = Field(min_length=1, max_length=64)
    category: Category
    impact: Impact
    urgency: Urgency
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=20, max_length=1200)
    indicators: list[str] = Field(default_factory=list, max_length=12)


class GateAResult(BaseModel):
    """Machine safety gate outcome.

    Answers one question only - is this output safe to emit into a downstream
    system without a human looking at it first?
    """

    model_config = ConfigDict(frozen=True)

    passed: bool
    violations: list[str] = Field(default_factory=list)


class GateBResult(BaseModel):
    """Human accountability gate outcome.

    Answers a different question - who is answerable for this decision, and
    must they see it before it takes effect?
    """

    model_config = ConfigDict(frozen=True)

    human_review_required: bool
    triggers: list[str] = Field(default_factory=list)
    accountable_role: str


class TraceStep(BaseModel):
    """One step of the reason-act-observe-reflect loop."""

    model_config = ConfigDict(frozen=True)

    attempt: int
    phase: str
    detail: str


class OutcomeStatus(str, Enum):
    EMITTED = "emitted"
    ESCALATED = "escalated"
    BLOCKED = "blocked"


class TriageOutcome(BaseModel):
    """The full, auditable result of triaging one incident."""

    model_config = ConfigDict(frozen=True)

    incident_id: str
    status: OutcomeStatus
    decision: TriageDecision | None
    gate_a: GateAResult
    gate_b: GateBResult | None
    trace: list[TraceStep] = Field(default_factory=list)

    @property
    def severity(self) -> Severity | None:
        return self.decision.severity if self.decision else None
