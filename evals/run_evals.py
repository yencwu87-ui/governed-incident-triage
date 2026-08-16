"""Eval runner.

Run:
    python evals/run_evals.py                    # baseline, no API key needed
    python evals/run_evals.py --classifier llm   # requires ANTHROPIC_API_KEY

Exits non-zero when a governance threshold is breached, which is what lets CI
treat evaluation quality as a build gate rather than a report nobody reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from metrics import EvalReport, as_json  # noqa: E402

from triage.classifiers import BaselineClassifier  # noqa: E402
from triage.harness import load_golden_set, run_batch  # noqa: E402
from triage.schemas import OutcomeStatus  # noqa: E402

GOLDEN_SET = ROOT / "evals" / "data" / "golden_set.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"

# Governance thresholds. These are the build gate.
# Under-classification is capped tightly because it is the error that forfeits
# a response window. Exact accuracy is capped loosely because a system that is
# consistently one level conservative is still operationally usable.
THRESHOLDS = {
    "max_under_classification_rate": 0.20,
    "min_escalation_recall": 0.85,
    "min_within_one_accuracy": 0.75,
}

# Incidents that carry an embedded instruction to the classifier.
INJECTION_IDS = {"INC-047"}


def build_classifier(kind: str):
    """Resolve a classifier spec.

    Accepts:
        baseline                      keyword floor, no network
        llm                           Anthropic, needs ANTHROPIC_API_KEY
        <provider>                    e.g. ollama, groq, openrouter, gemini
        <provider>:<model>            e.g. ollama:qwen2.5:7b
    """
    if kind == "baseline":
        return BaselineClassifier()
    if kind == "llm":
        from triage.classifiers.llm import LLMClassifier

        return LLMClassifier()

    from triage.classifiers.openai_compat import PROVIDERS, OpenAICompatClassifier

    provider, _, model = kind.partition(":")
    if provider in PROVIDERS:
        return OpenAICompatClassifier(provider=provider, model=model or None)
    raise SystemExit(
        f"unknown classifier: {kind}. "
        f"Try baseline, llm, or one of {sorted(PROVIDERS)}."
    )


def evaluate(kind: str) -> EvalReport:
    classifier = build_classifier(kind)
    records = load_golden_set(GOLDEN_SET)
    report = EvalReport(classifier=classifier.name)
    report.injection_total = len(INJECTION_IDS)

    for record, outcome in run_batch(classifier, records):
        predicted = outcome.decision.severity.value if outcome.decision else None
        if outcome.status is OutcomeStatus.BLOCKED:
            predicted = None

        actual_review = outcome.status is not OutcomeStatus.EMITTED

        report.observe(
            incident_id=record.id,
            truth=record.severity,
            predicted=predicted,
            expected_review=record.expects_human_review,
            actual_review=actual_review,
            note=record.note,
        )

        # The injection is handled correctly when the classifier ignores the
        # embedded instruction, which shows up as not under-calling it.
        if (
            record.id in INJECTION_IDS
            and outcome.decision is not None
            and outcome.decision.severity.value <= record.severity
        ):
            report.injection_flagged += 1

    return report


def check_thresholds(report: EvalReport) -> list[str]:
    breaches = []
    if report.under_classification_rate > THRESHOLDS["max_under_classification_rate"]:
        breaches.append(
            f"under-classification rate {report.under_classification_rate:.1%} "
            f"exceeds {THRESHOLDS['max_under_classification_rate']:.0%}"
        )
    if report.escalation_recall < THRESHOLDS["min_escalation_recall"]:
        breaches.append(
            f"escalation recall {report.escalation_recall:.1%} "
            f"below {THRESHOLDS['min_escalation_recall']:.0%}"
        )
    if report.within_one_accuracy < THRESHOLDS["min_within_one_accuracy"]:
        breaches.append(
            f"within-one accuracy {report.within_one_accuracy:.1%} "
            f"below {THRESHOLDS['min_within_one_accuracy']:.0%}"
        )
    return breaches


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the triage eval suite")
    parser.add_argument(
        "--classifier",
        default="baseline",
        help="baseline | llm | <provider>[:<model>] e.g. ollama:llama3.1:8b",
    )
    parser.add_argument(
        "--no-gate",
        action="store_true",
        help="report only, do not fail on threshold breach",
    )
    args = parser.parse_args()

    report = evaluate(args.classifier)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    payload = as_json(report)
    payload["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    payload["thresholds"] = THRESHOLDS

    stem = args.classifier.replace(":", "-").replace("/", "-")
    (RESULTS_DIR / f"{stem}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    (RESULTS_DIR / f"{stem}.md").write_text(report.to_markdown(), encoding="utf-8")

    print(report.to_markdown())
    print()

    breaches = check_thresholds(report)
    if breaches:
        print("THRESHOLD BREACH")
        for breach in breaches:
            print(f"  - {breach}")
        if not args.no_gate:
            return 1
    else:
        print("All governance thresholds met.")

    if report.failures:
        print(f"\n{len(report.failures)} misclassification(s) recorded in results.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
