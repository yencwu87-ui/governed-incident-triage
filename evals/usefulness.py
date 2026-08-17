"""Usefulness tests.

Accuracy asks whether the classifier is right. Usefulness asks whether anyone
should run it. Those are different questions and the second one is rarely
asked, because the answer is often no.

The honest benchmark is not another classifier. It is the trivial policy the
system replaces - a human reads every ticket. That policy has perfect
escalation recall and zero automation. Any system claiming to be useful has to
buy meaningful review-burden reduction at an acceptable cost in missed
escalations. If it cannot, the correct engineering decision is to delete it and
keep the human.

Four experiments.

1. Null-policy comparison. Trivial baselines with no intelligence at all.
2. The burden / miss frontier. Where each policy sits, and which are dominated.
3. Gate ablation. What escapes when each gate is removed.
4. Coverage sensitivity. What the headline metric does when the classifier
   refuses to answer.

    python evals/usefulness.py
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from backtest import NoisyOracle  # noqa: E402

from triage.agent import triage  # noqa: E402
from triage.classifiers import BaselineClassifier  # noqa: E402
from triage.gates import gate_a, gate_b  # noqa: E402
from triage.harness import load_golden_set  # noqa: E402
from triage.rubric import derive_severity  # noqa: E402
from triage.schemas import (  # noqa: E402
    Category,
    Impact,
    OutcomeStatus,
    TriageDecision,
    Urgency,
)

GOLDEN_SET = ROOT / "evals" / "data" / "golden_set.jsonl"
RESULTS = ROOT / "evals" / "results"
SEED = 20260817

# An incident is consequential when a human genuinely needed to see it.
CONSEQUENTIAL = {"SEV1", "SEV2"}


# --------------------------------------------------------------------------
# Trivial policies. No intelligence. These are what the system must beat.
# --------------------------------------------------------------------------


class FixedPolicy:
    """Assigns the same impact and urgency to every incident."""

    def __init__(self, impact: Impact, urgency: Urgency, label: str):
        self.name = label
        self._impact, self._urgency = impact, urgency

    def classify(self, incident_id, text, feedback=None):
        return TriageDecision(
            incident_id=incident_id,
            category=Category.AVAILABILITY,
            impact=self._impact,
            urgency=self._urgency,
            severity=derive_severity(self._impact, self._urgency),
            confidence=0.99,
            rationale="Fixed policy applied without reading the incident text.",
            indicators=["fixed"],
        )


class RandomPolicy:
    name = "random-severity"

    def __init__(self, seed=SEED):
        self._rng = random.Random(seed)

    def classify(self, incident_id, text, feedback=None):
        impact = self._rng.choice(list(Impact))
        urgency = self._rng.choice(list(Urgency))
        return TriageDecision(
            incident_id=incident_id,
            category=self._rng.choice(list(Category)),
            impact=impact,
            urgency=urgency,
            severity=derive_severity(impact, urgency),
            confidence=0.99,
            rationale="Random assignment, included as a floor for comparison.",
            indicators=["random"],
        )


def measure(classifier, records) -> dict:
    """Operational measures, not accuracy measures.

    review_burden      fraction of incidents a human must look at
    dangerous_misses   consequential incidents auto-emitted with no human
    safe_automation    correctly auto-emitted low-consequence incidents
    """
    burden = 0
    dangerous = []
    safe_auto = 0
    wrong_auto = 0

    for record in records:
        outcome = triage(classifier, record.id, record.text)
        needs_human = outcome.status is not OutcomeStatus.EMITTED
        if needs_human:
            burden += 1
            continue
        # Auto-emitted. Was that safe?
        if record.severity in CONSEQUENTIAL:
            dangerous.append(record.id)
        elif outcome.decision and outcome.decision.severity.value == record.severity:
            safe_auto += 1
        else:
            wrong_auto += 1

    total = len(records)
    consequential_total = sum(1 for r in records if r.severity in CONSEQUENTIAL)
    return {
        "classifier": getattr(classifier, "name", "unknown"),
        "review_burden": round(burden / total, 3),
        "burden_reduction": round(1 - burden / total, 3),
        "dangerous_misses": len(dangerous),
        "dangerous_miss_rate": round(len(dangerous) / consequential_total, 3),
        "safe_automation": safe_auto,
        "auto_emitted_but_wrong": wrong_auto,
        "dangerous_ids": dangerous,
    }


def experiment_null_policies(records) -> list[dict]:
    policies = [
        FixedPolicy(Impact.EXTENSIVE, Urgency.CRITICAL, "always-SEV1 (escalate all)"),
        FixedPolicy(Impact.MINOR, Urgency.LOW, "always-SEV4 (escalate none)"),
        FixedPolicy(Impact.MODERATE, Urgency.MEDIUM, "always-SEV3 (modal guess)"),
        RandomPolicy(),
        BaselineClassifier(),
        NoisyOracle(records, error_rate=0.0),
        NoisyOracle(records, error_rate=0.33, calibrated=False),
    ]
    return [measure(p, records) for p in policies]


def experiment_gate_ablation(records) -> dict:
    """What escapes when a gate is removed?

    Runs the classifier directly, bypassing the agent loop, and counts what
    each gate is actually stopping.
    """
    classifier = BaselineClassifier()
    gate_a_blocks = 0
    escalated_by_b = 0
    consequential_caught_by_b = 0
    consequential_total = 0

    # Ungated: whatever the classifier says goes straight through.
    ungated_dangerous = 0

    for record in records:
        decision = classifier.classify(record.id, record.text)
        a = gate_a(decision)
        if not a.passed:
            gate_a_blocks += 1
            continue
        b = gate_b(decision)
        if b.human_review_required:
            escalated_by_b += 1

        if record.severity in CONSEQUENTIAL:
            consequential_total += 1
            if b.human_review_required:
                consequential_caught_by_b += 1
            # Ungated, this reaches a downstream system unreviewed.
            ungated_dangerous += 1

    return {
        "gate_a_blocks": gate_a_blocks,
        "gate_b_escalations": escalated_by_b,
        "consequential_total": consequential_total,
        "consequential_reaching_human_with_gate_b": consequential_caught_by_b,
        "consequential_reaching_human_without_gate_b": 0,
        "consequential_unreviewed_if_ungated": ungated_dangerous,
    }


def experiment_coverage_sensitivity(records) -> list[dict]:
    """What does under-classification do as the classifier refuses more?

    A blocked incident cannot be under-classified, so refusing to answer
    improves the headline metric. This quantifies that blind spot.
    """

    class RefusingClassifier:
        def __init__(self, refuse_fraction, seed=SEED):
            self.name = f"refuses-{refuse_fraction:.0%}"
            self._inner = BaselineClassifier()
            self._frac = refuse_fraction
            self._rng = random.Random(seed)

        def classify(self, incident_id, text, feedback=None):
            if self._rng.random() < self._frac:
                # Emitting a rubric-incoherent decision is the cheapest way to
                # trip Gate A deterministically.
                return TriageDecision(
                    incident_id=incident_id,
                    category=Category.AVAILABILITY,
                    impact=Impact.MINOR,
                    urgency=Urgency.LOW,
                    severity=derive_severity(Impact.EXTENSIVE, Urgency.CRITICAL),
                    confidence=0.99,
                    rationale="Deliberately incoherent output to trigger Gate A.",
                    indicators=["refusal"],
                )
            return self._inner.classify(incident_id, text, feedback)

    from metrics import EvalReport

    rows = []
    for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
        classifier = RefusingClassifier(frac)
        report = EvalReport(classifier=classifier.name)
        for record in records:
            outcome = triage(classifier, record.id, record.text)
            predicted = (
                outcome.decision.severity.value
                if outcome.decision and outcome.status is not OutcomeStatus.BLOCKED
                else None
            )
            report.observe(
                incident_id=record.id,
                truth=record.severity,
                predicted=predicted,
                expected_review=record.expects_human_review,
                actual_review=outcome.status is not OutcomeStatus.EMITTED,
                note=record.note,
            )
        rows.append(
            {
                "refusal_rate": frac,
                "scored": report.scored,
                "blocked": report.blocked,
                "under_classification_rate": round(report.under_classification_rate, 3),
                "within_one_accuracy": round(report.within_one_accuracy, 3),
                "escalation_recall": round(report.escalation_recall, 3),
            }
        )
    return rows


def main() -> int:
    records = load_golden_set(GOLDEN_SET)
    results = {
        "null_policies": experiment_null_policies(records),
        "gate_ablation": experiment_gate_ablation(records),
        "coverage_sensitivity": experiment_coverage_sensitivity(records),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "usefulness.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )

    print("1. NULL-POLICY COMPARISON")
    header = f"   {'policy':<34} {'burden':>7} {'saved':>7} {'dang.miss':>10}"
    print(f"{header} {'safe auto':>10}")
    for row in results["null_policies"]:
        print(
            f"   {row['classifier']:<34} {row['review_burden']:>7.1%} "
            f"{row['burden_reduction']:>7.1%} "
            f"{row['dangerous_misses']:>4} ({row['dangerous_miss_rate']:>4.1%}) "
            f"{row['safe_automation']:>9}"
        )

    print("\n2. GATE ABLATION")
    for key, value in results["gate_ablation"].items():
        print(f"   {key:<48} {value}")

    print("\n3. COVERAGE SENSITIVITY")
    head = f"   {'refuse':>7} {'scored':>7} {'blocked':>8} {'under':>7}"
    print(f"{head} {'within1':>8} {'escrec':>7}")
    for row in results["coverage_sensitivity"]:
        print(
            f"   {row['refusal_rate']:>7.0%} {row['scored']:>7} {row['blocked']:>8} "
            f"{row['under_classification_rate']:>7.3f} "
            f"{row['within_one_accuracy']:>8.3f} {row['escalation_recall']:>7.3f}"
        )

    print(f"\nWritten to {RESULTS / 'usefulness.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
