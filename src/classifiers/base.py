"""Classifier interface.

Two implementations ship with the project - a deterministic rule baseline and
an LLM classifier. Both satisfy the same contract, which is what makes the
comparison in the eval report meaningful. A model that cannot beat a keyword
baseline on this task is not earning its cost or its governance overhead.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import TriageDecision


class ClassifierError(RuntimeError):
    """Raised when a classifier cannot produce a parseable decision.

    This is distinct from producing a poor decision. A parse failure never
    reaches Gate A - there is nothing to gate.
    """


@runtime_checkable
class Classifier(Protocol):
    """Anything that turns incident text into a validated TriageDecision."""

    name: str

    def classify(
        self,
        incident_id: str,
        text: str,
        feedback: str | None = None,
    ) -> TriageDecision:
        """Classify one incident.

        Args:
            incident_id: Stable identifier carried through to the decision.
            text: Free-text incident description.
            feedback: Gate A violations from a prior attempt, if this is a
                retry. Implementations may ignore it.
        """
        ...
