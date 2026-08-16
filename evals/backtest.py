"""Backtest suite.

Three experiments the single eval run cannot answer.

1. Failure taxonomy. Not how many the baseline got wrong, but what kind of
   incident it systematically cannot read.

2. Degradation curve. The governance question nobody asks - how bad can the
   classifier get before the gates stop protecting anything? Run a synthetic
   classifier at controlled error rates and watch escalation recall fall.
   This measures the protective margin of the design rather than the quality
   of any one model.

3. Threshold sweep. The Gate B confidence trigger trades escalation precision
   against recall. The current value was set by judgement. This shows what it
   actually buys.

Everything here is deterministic given the seed. No API key required.

    python evals/backtest.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from metrics import EvalReport  # noqa: E402

from triage.agent import triage  # noqa: E402
from triage.classifiers import BaselineClassifier  # noqa: E402
from triage.gates import gate_b  # noqa: E402
from triage.harness import load_golden_set, run_batch  # noqa: E402
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
SEED = 20260814

IMPACT_ORDER = [Impact.MINOR, Impact.MODERATE, Impact.SIGNIFICANT, Impact.EXTENSIVE]
URGENCY_ORDER = [Urgency.LOW, Urgency.MEDIUM, Urgency.HIGH, Urgency.CRITICAL]

# Incident patterns that surface vocabulary cannot reach. Assigned by hand from
# the golden set notes, used to group failures rather than to label them.
PATTERNS: dict[str, set[str]] = {
    "second_order_impact": {"INC-036", "INC-054", "INC-039", "INC-007", "INC-033"},
    "historic_event_present_urgency": {"INC-018", "INC-050", "INC-060", "INC-029"},
    "alarming_words_contained_blast_radius": {"INC-042", "INC-023", "INC-010"},
    "regulatory_vocabulary_low_urgency": {"INC-028", "INC-014", "INC-057"},
    "scale_stated_numerically": {"INC-027", "INC-035", "INC-048", "INC-030"},
    "prompt_injection": {"INC-047"},
}


# --------------------------------------------------------------------------
# Experiment 1 - failure taxonomy
# --------------------------------------------------------------------------


def experiment_failure_taxonomy() -> dict:
    records = {r.id: r for r in load_golden_set(GOLDEN_SET)}
    classifier = BaselineClassifier()

    misses: list[dict] = []
    for record, outcome in run_batch(classifier, records.values()):
        if outcome.decision is None:
            continue
        predicted = outcome.decision.severity.value
        if predicted == record.severity:
            continue
        misses.append(
            {
                "id": record.id,
                "truth": record.severity,
                "predicted": predicted,
                "direction": (
                    "under" if int(predicted[-1]) > int(record.severity[-1]) else "over"
                ),
                "truth_axes": f"{record.impact} x {record.urgency}",
                "predicted_axes": (
                    f"{outcome.decision.impact.value} x "
                    f"{outcome.decision.urgency.value}"
                ),
                "escalated_anyway": outcome.status is not OutcomeStatus.EMITTED,
            }
        )

    # Which axis went wrong more often?
    axis_errors = Counter()
    for record, outcome in run_batch(classifier, records.values()):
        if outcome.decision is None:
            continue
        if outcome.decision.impact.value != record.impact:
            axis_errors["impact"] += 1
        if outcome.decision.urgency.value != record.urgency:
            axis_errors["urgency"] += 1

    missed_ids = {m["id"] for m in misses}
    by_pattern = {
        name: {
            "in_set": len(ids),
            "missed": len(ids & missed_ids),
            "miss_rate": round(len(ids & missed_ids) / len(ids), 2),
        }
        for name, ids in PATTERNS.items()
    }

    # The critical safety question - of the misses, how many still reached a
    # human because Gate B caught them on some other trigger?
    rescued = sum(
        1 for m in misses if m["direction"] == "under" and m["escalated_anyway"]
    )
    under_total = sum(1 for m in misses if m["direction"] == "under")

    return {
        "total_misses": len(misses),
        "axis_errors": dict(axis_errors),
        "by_pattern": by_pattern,
        "under_classified": under_total,
        "under_classified_still_escalated": rescued,
        "silent_under_classifications": under_total - rescued,
        "misses": misses,
    }


# --------------------------------------------------------------------------
# Experiment 2 - degradation curve
# --------------------------------------------------------------------------


class NoisyOracle:
    """A classifier that knows the truth and then corrupts it at a fixed rate.

    Used to answer a question about the *design* rather than about any model.
    At what classifier error rate do the gates stop protecting anything?
    """

    def __init__(
        self,
        records,
        error_rate: float,
        seed: int = SEED,
        corrupt_category: bool = True,
        calibrated: bool = True,
    ):
        self.name = f"oracle-noise-{error_rate:.2f}"
        self._truth = {r.id: r for r in records}
        self._error_rate = error_rate
        self._corrupt_category = corrupt_category
        self._calibrated = calibrated
        self._rng = random.Random(seed)

    def _perturb(self, value, order):
        idx = order.index(value)
        step = self._rng.choice([-1, 1])
        return order[max(0, min(len(order) - 1, idx + step))]

    def classify(self, incident_id, text, feedback=None):
        record = self._truth[incident_id]
        impact = Impact(record.impact)
        urgency = Urgency(record.urgency)

        category = Category(record.category)

        corrupted = False
        if self._rng.random() < self._error_rate:
            roll = self._rng.random()
            if roll < 0.4:
                impact = self._perturb(impact, IMPACT_ORDER)
            elif roll < 0.8:
                urgency = self._perturb(urgency, URGENCY_ORDER)
            elif self._corrupt_category:
                # Category errors are the ones that defeat Gate B, because the
                # sensitive-category trigger is the control that rescues most
                # severity misjudgements.
                category = self._rng.choice([c for c in Category if c is not category])
            else:
                impact = self._perturb(impact, IMPACT_ORDER)
            corrupted = True

        # A perfectly calibrated classifier lowers its confidence exactly when
        # it is wrong. Real models do not. The overconfident variant holds
        # confidence high regardless, which is the realistic case and the one
        # that tests whether the gates work without calibration propping them up.
        confidence = 0.55 if (self._calibrated and corrupted) else 0.88

        return TriageDecision(
            incident_id=incident_id,
            category=category,
            impact=impact,
            urgency=urgency,
            severity=derive_severity(impact, urgency),
            confidence=confidence,
            rationale=(
                "Synthetic oracle output generated for degradation testing "
                "at a controlled error rate."
            ),
            indicators=["synthetic"],
        )


def _degradation_curve(
    records, corrupt_category: bool, calibrated: bool = True
) -> list[dict]:
    curve = []
    for error_rate in [round(0.05 * i, 2) for i in range(13)]:
        oracle = NoisyOracle(
            records,
            error_rate,
            corrupt_category=corrupt_category,
            calibrated=calibrated,
        )
        report = EvalReport(classifier=oracle.name)

        for record in records:
            outcome = triage(oracle, record.id, record.text)
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

        curve.append(
            {
                "error_rate": error_rate,
                "exact_accuracy": round(report.exact_accuracy, 3),
                "under_classification_rate": round(report.under_classification_rate, 3),
                "escalation_recall": round(report.escalation_recall, 3),
                "escalation_precision": round(report.escalation_precision, 3),
                "blocked": report.blocked,
            }
        )
    return curve


def _breach(curve: list[dict]) -> float | None:
    return next((p["error_rate"] for p in curve if p["escalation_recall"] < 0.85), None)


def experiment_degradation() -> dict:
    """Two curves, because the difference between them is the finding.

    Severity-only corruption barely dents escalation recall - a SEV1 misread as
    SEV2 still escalates. Category corruption is what actually defeats Gate B,
    because the sensitive-category trigger is doing most of the rescuing.
    """
    records = load_golden_set(GOLDEN_SET)
    variants = {
        "calibrated_severity_only": _degradation_curve(records, False, True),
        "calibrated_with_category": _degradation_curve(records, True, True),
        "overconfident_with_category": _degradation_curve(records, True, False),
    }
    return {
        name: {
            "curve": curve,
            "escalation_recall_breach_at_error_rate": _breach(curve),
        }
        for name, curve in variants.items()
    }


# --------------------------------------------------------------------------
# Experiment 3 - Gate B threshold sweep
# --------------------------------------------------------------------------


def experiment_threshold_sweep() -> dict:
    """What does the Gate B confidence trigger actually buy?

    Re-runs Gate B at a range of confidence thresholds against a fixed set of
    decisions, holding the consequence and category triggers constant.
    """
    import triage.gates as gates_module

    records = load_golden_set(GOLDEN_SET)
    classifier = BaselineClassifier()
    decisions = []
    for record, outcome in run_batch(classifier, records):
        if outcome.decision is not None:
            decisions.append((record, outcome.decision))

    original = gates_module.REVIEW_CONFIDENCE_THRESHOLD
    sweep = []
    try:
        for threshold in [round(0.05 * i, 2) for i in range(0, 21)]:
            gates_module.REVIEW_CONFIDENCE_THRESHOLD = threshold
            tp = fp = fn = tn = 0
            for record, decision in decisions:
                escalated = gate_b(decision).human_review_required
                if record.expects_human_review and escalated:
                    tp += 1
                elif record.expects_human_review and not escalated:
                    fn += 1
                elif escalated:
                    fp += 1
                else:
                    tn += 1
            sweep.append(
                {
                    "threshold": threshold,
                    "escalation_rate": round((tp + fp) / len(decisions), 3),
                    "recall": round(tp / (tp + fn), 3) if (tp + fn) else 0.0,
                    "precision": round(tp / (tp + fp), 3) if (tp + fp) else 0.0,
                    "auto_emitted": tn,
                }
            )
    finally:
        gates_module.REVIEW_CONFIDENCE_THRESHOLD = original

    # The value worth knowing - the lowest threshold that keeps recall at 1.0
    perfect = [p for p in sweep if p["recall"] >= 0.999]
    return {
        "sweep": sweep,
        "lowest_threshold_with_full_recall": (
            min(p["threshold"] for p in perfect) if perfect else None
        ),
        "current_threshold": original,
    }


def main() -> int:
    random.seed(SEED)
    results = {
        "seed": SEED,
        "failure_taxonomy": experiment_failure_taxonomy(),
        "degradation": experiment_degradation(),
        "threshold_sweep": experiment_threshold_sweep(),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "backtest.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )

    ft = results["failure_taxonomy"]
    print("FAILURE TAXONOMY")
    print(f"  misses: {ft['total_misses']}  axis errors: {ft['axis_errors']}")
    print(f"  under-classified: {ft['under_classified']}")
    print(f"  ... still escalated by Gate B: {ft['under_classified_still_escalated']}")
    print(f"  ... silent (no human): {ft['silent_under_classifications']}")
    print("  by pattern:")
    for name, stats in ft["by_pattern"].items():
        print(
            f"    {name:42s} {stats['missed']}/{stats['in_set']}  "
            f"({stats['miss_rate']:.0%})"
        )

    print("\nDEGRADATION CURVE")
    for label in (
        "calibrated_severity_only",
        "calibrated_with_category",
        "overconfident_with_category",
    ):
        block = results["degradation"][label]
        print(f"  [{label}]")
        print("  err   exact   under   esc_recall   esc_prec")
        for point in block["curve"]:
            print(
                f"  {point['error_rate']:.2f}  {point['exact_accuracy']:.3f}  "
                f"{point['under_classification_rate']:.3f}   "
                f"{point['escalation_recall']:.3f}        "
                f"{point['escalation_precision']:.3f}"
            )
        print(
            "  escalation recall breaches 85% at error rate: "
            f"{block['escalation_recall_breach_at_error_rate']}\n"
        )

    ts = results["threshold_sweep"]
    print("\nGATE B THRESHOLD SWEEP")
    print(f"  current threshold: {ts['current_threshold']}")
    print(
        "  lowest threshold with full recall: "
        f"{ts['lowest_threshold_with_full_recall']}"
    )
    print("  thr    esc_rate  recall  precision  auto_emitted")
    for point in ts["sweep"][::2]:
        print(
            f"  {point['threshold']:.2f}   {point['escalation_rate']:.3f}     "
            f"{point['recall']:.3f}   {point['precision']:.3f}      "
            f"{point['auto_emitted']}"
        )

    print(f"\nWritten to {RESULTS / 'backtest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["NoisyOracle", "main", "replace"]
