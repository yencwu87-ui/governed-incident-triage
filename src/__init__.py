"""Governed incident triage - a classifier with its accountability model attached."""

from .agent import triage
from .gates import gate_a, gate_b
from .harness import IncidentRecord, load_golden_set, run_batch
from .rubric import derive_severity, is_consistent
from .schemas import (
    Category,
    GateAResult,
    GateBResult,
    Impact,
    OutcomeStatus,
    Severity,
    TriageDecision,
    TriageOutcome,
    Urgency,
)

__version__ = "0.1.0"

__all__ = [
    "Category",
    "GateAResult",
    "GateBResult",
    "Impact",
    "IncidentRecord",
    "OutcomeStatus",
    "Severity",
    "TriageDecision",
    "TriageOutcome",
    "Urgency",
    "derive_severity",
    "gate_a",
    "gate_b",
    "is_consistent",
    "load_golden_set",
    "run_batch",
    "triage",
]
