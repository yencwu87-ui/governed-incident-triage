"""Command line entry point.

    triage "the payment gateway is down for all customers"
    triage --classifier llm --json "disk full on the primary array"
"""

from __future__ import annotations

import argparse
import json
import sys

from .agent import triage as run_triage
from .classifiers import BaselineClassifier


def _build(kind: str):
    if kind == "baseline":
        return BaselineClassifier()
    from .classifiers.llm import LLMClassifier

    return LLMClassifier()


def main() -> int:
    parser = argparse.ArgumentParser(prog="triage", description="Triage one incident")
    parser.add_argument("text", nargs="?", help="incident description (or read stdin)")
    parser.add_argument("--id", default="INC-ADHOC")
    parser.add_argument("--classifier", default="baseline", choices=["baseline", "llm"])
    parser.add_argument("--json", action="store_true", help="emit the full outcome")
    args = parser.parse_args()

    text = args.text or sys.stdin.read()
    if not text.strip():
        parser.error("no incident text supplied")

    outcome = run_triage(_build(args.classifier), args.id, text.strip())

    if args.json:
        print(outcome.model_dump_json(indent=2))
        return 0

    print(f"status    {outcome.status.value}")
    if outcome.decision:
        d = outcome.decision
        print(f"severity  {d.severity.value}  ({d.impact.value} x {d.urgency.value})")
        print(f"category  {d.category.value}")
        print(f"confidence {d.confidence:.2f}")
        print(f"rationale {d.rationale}")
    if not outcome.gate_a.passed:
        print("gate A    " + "; ".join(outcome.gate_a.violations))
    if outcome.gate_b:
        print(f"gate B    accountable: {outcome.gate_b.accountable_role}")
        for trigger in outcome.gate_b.triggers:
            print(f"          - {trigger}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "json"]
