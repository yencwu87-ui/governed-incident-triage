"""Batch harness.

Thin by design. Everything interesting happens in agent.py and gates.py; this
just iterates and keeps the run reproducible and inspectable.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .agent import triage
from .classifiers.base import Classifier
from .schemas import TriageOutcome


@dataclass(frozen=True)
class IncidentRecord:
    """One labelled incident from the golden set."""

    id: str
    text: str
    category: str
    impact: str
    urgency: str
    severity: str
    expects_human_review: bool
    note: str = ""

    @classmethod
    def from_dict(cls, payload: dict) -> IncidentRecord:
        return cls(
            id=payload["id"],
            text=payload["text"],
            category=payload["category"],
            impact=payload["impact"],
            urgency=payload["urgency"],
            severity=payload["severity"],
            expects_human_review=bool(payload["expects_human_review"]),
            note=payload.get("note", ""),
        )


def load_golden_set(path: str | Path) -> list[IncidentRecord]:
    """Read the labelled evaluation set from JSONL."""
    records: list[IncidentRecord] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                records.append(IncidentRecord.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError) as exc:
                raise ValueError(f"{path}:{line_no} is malformed: {exc}") from exc
    return records


def run_batch(
    classifier: Classifier,
    records: Iterable[IncidentRecord],
) -> Iterator[tuple[IncidentRecord, TriageOutcome]]:
    """Triage every record, yielding the record alongside its outcome."""
    for record in records:
        yield record, triage(classifier, record.id, record.text)
