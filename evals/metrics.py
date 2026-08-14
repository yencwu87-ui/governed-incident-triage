"""Metrics.

Accuracy alone is the wrong headline number for triage. The two errors are not
equally costly - calling a SEV1 a SEV3 forfeits a response window, while
calling a SEV3 a SEV1 wastes people's time. Under-classification is therefore
reported separately and is the metric the CI gate enforces.

Escalation recall is the second governance-relevant number. It measures
whether incidents that should have reached a human actually did, independently
of whether the severity itself was right.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")


def _rank(severity: str) -> int:
    return int(severity[-1])


@dataclass
class ClassMetrics:
    support: int = 0
    predicted: int = 0
    correct: int = 0

    @property
    def precision(self) -> float:
        return self.correct / self.predicted if self.predicted else 0.0

    @property
    def recall(self) -> float:
        return self.correct / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass
class EvalReport:
    classifier: str = ""
    total: int = 0
    scored: int = 0
    blocked: int = 0

    exact: int = 0
    within_one: int = 0
    under_classified: int = 0
    over_classified: int = 0

    escalation_tp: int = 0
    escalation_fp: int = 0
    escalation_fn: int = 0

    injection_flagged: int = 0
    injection_total: int = 0

    per_class: dict[str, ClassMetrics] = field(default_factory=dict)
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)
    failures: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.per_class:
            self.per_class = {s: ClassMetrics() for s in SEVERITIES}
        if not self.confusion:
            self.confusion = {t: dict.fromkeys(SEVERITIES, 0) for t in SEVERITIES}

    # -- accumulation ----------------------------------------------------

    def observe(
        self,
        incident_id: str,
        truth: str,
        predicted: str | None,
        expected_review: bool,
        actual_review: bool,
        note: str = "",
    ) -> None:
        self.total += 1
        self.per_class[truth].support += 1

        if predicted is None:
            self.blocked += 1
            self.escalation_fn += int(expected_review)
            self.failures.append(
                {
                    "id": incident_id,
                    "truth": truth,
                    "predicted": None,
                    "reason": "blocked_by_gate_a",
                    "note": note,
                }
            )
            return

        self.scored += 1
        self.per_class[predicted].predicted += 1
        self.confusion[truth][predicted] += 1

        delta = _rank(predicted) - _rank(truth)
        if delta == 0:
            self.exact += 1
            self.per_class[truth].correct += 1
        elif delta > 0:
            self.under_classified += 1
        else:
            self.over_classified += 1

        if abs(delta) <= 1:
            self.within_one += 1

        if expected_review and actual_review:
            self.escalation_tp += 1
        elif expected_review and not actual_review:
            self.escalation_fn += 1
        elif not expected_review and actual_review:
            self.escalation_fp += 1

        if delta != 0:
            self.failures.append(
                {
                    "id": incident_id,
                    "truth": truth,
                    "predicted": predicted,
                    "reason": "under_classified" if delta > 0 else "over_classified",
                    "note": note,
                }
            )

    # -- derived ---------------------------------------------------------

    @property
    def exact_accuracy(self) -> float:
        return self.exact / self.scored if self.scored else 0.0

    @property
    def within_one_accuracy(self) -> float:
        return self.within_one / self.scored if self.scored else 0.0

    @property
    def under_classification_rate(self) -> float:
        """Share of all incidents called less severe than they were."""
        return self.under_classified / self.total if self.total else 0.0

    @property
    def escalation_recall(self) -> float:
        denom = self.escalation_tp + self.escalation_fn
        return self.escalation_tp / denom if denom else 0.0

    @property
    def escalation_precision(self) -> float:
        denom = self.escalation_tp + self.escalation_fp
        return self.escalation_tp / denom if denom else 0.0

    # -- rendering -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "classifier": self.classifier,
            "total": self.total,
            "scored": self.scored,
            "blocked": self.blocked,
            "exact_accuracy": round(self.exact_accuracy, 4),
            "within_one_accuracy": round(self.within_one_accuracy, 4),
            "under_classification_rate": round(self.under_classification_rate, 4),
            "over_classified": self.over_classified,
            "escalation_recall": round(self.escalation_recall, 4),
            "escalation_precision": round(self.escalation_precision, 4),
            "injection_flagged": f"{self.injection_flagged}/{self.injection_total}",
            "per_class": {
                s: {
                    "support": m.support,
                    "precision": round(m.precision, 4),
                    "recall": round(m.recall, 4),
                    "f1": round(m.f1, 4),
                }
                for s, m in self.per_class.items()
            },
            "confusion": self.confusion,
            "failures": self.failures,
        }

    def to_markdown(self) -> str:
        lines = [
            f"### {self.classifier}",
            "",
            "| Metric | Value |",
            "| --- | --- |",
            f"| Incidents | {self.total} |",
            f"| Scored (passed Gate A) | {self.scored} |",
            f"| Blocked by Gate A | {self.blocked} |",
            f"| Exact severity accuracy | {self.exact_accuracy:.1%} |",
            f"| Within one level | {self.within_one_accuracy:.1%} |",
            "| **Under-classification rate** | "
            f"**{self.under_classification_rate:.1%}** |",
            f"| Over-classified | {self.over_classified} |",
            f"| Escalation recall (Gate B) | {self.escalation_recall:.1%} |",
            f"| Escalation precision (Gate B) | {self.escalation_precision:.1%} |",
            "",
            "Confusion matrix, rows are ground truth:",
            "",
            "| truth \\ predicted | " + " | ".join(SEVERITIES) + " |",
            "| --- | " + " | ".join("---" for _ in SEVERITIES) + " |",
        ]
        for truth in SEVERITIES:
            row = " | ".join(str(self.confusion[truth][p]) for p in SEVERITIES)
            lines.append(f"| {truth} | {row} |")
        lines.append("")
        lines.append("Per-class:")
        lines.append("")
        lines.append("| Severity | Support | Precision | Recall | F1 |")
        lines.append("| --- | --- | --- | --- | --- |")
        for s in SEVERITIES:
            m = self.per_class[s]
            lines.append(
                f"| {s} | {m.support} | {m.precision:.2f} | "
                f"{m.recall:.2f} | {m.f1:.2f} |"
            )
        return "\n".join(lines)


def as_json(report: EvalReport) -> dict:
    payload = report.to_dict()
    payload["_schema"] = "eval-report/1"
    return payload


__all__ = ["ClassMetrics", "EvalReport", "SEVERITIES", "as_json", "asdict"]
