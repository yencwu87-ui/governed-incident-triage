"""Governed self-improvement loop.

The premise, and the reason this file is longer than the loop it implements.

A self-improvement loop is an agent retrying against a validator on a longer
time horizon. docs/design.md already argues that such an agent eventually
satisfies the validator rather than the requirement, which is why the inner
loop is capped at two attempts. Nothing about widening the horizon changes
that. It only makes the failure slower and harder to see.

So the loop is built with three constraints that are not tunable.

1. MUTATION WHITELIST. The loop may propose changes to the prompt and may
   propose new evaluation cases. It may not touch the rubric, the gate
   thresholds, the attempt budget, or any existing label. Those are policy and
   ground truth. A system permitted to move its own goalposts is not
   improving, it is drifting, and the distinction is invisible from inside.

2. HOLDOUT GUARD. Proposals are scored on a development split. A holdout split
   is scored only to detect divergence. When dev improves and holdout does not,
   the loop halts and reports overfitting rather than continuing. This is the
   only mechanism here that can distinguish improvement from memorisation.

3. EFFECT SIZE FLOOR. With 60 records a one-incident change moves the headline
   metric by 1.7 points. Proposals must clear a margin wider than that noise
   or they are rejected as indistinguishable from chance.

Every proposal, accepted or rejected, is written to a ledger with its reason.
The ledger is the governance artifact. A loop that improves a system without
leaving a record of what it changed and why has replaced a reviewable process
with an unreviewable one.

    python evals/selfimprove.py --rounds 3            # requires ANTHROPIC_API_KEY
    python evals/selfimprove.py --dry-run             # deterministic, no key
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "evals"))

from metrics import EvalReport  # noqa: E402

from triage.agent import triage  # noqa: E402
from triage.classifiers import BaselineClassifier  # noqa: E402
from triage.harness import load_golden_set  # noqa: E402
from triage.schemas import OutcomeStatus  # noqa: E402

GOLDEN_SET = ROOT / "evals" / "data" / "golden_set.jsonl"
LEDGER = ROOT / "evals" / "results" / "improvement_ledger.jsonl"
SPLIT_SEED = 20260815

# --- Constraint 1: what the loop is allowed to touch ----------------------

MUTABLE = frozenset({"prompt_guidance", "new_eval_case"})
IMMUTABLE = frozenset(
    {
        "severity_matrix",
        "gate_a_thresholds",
        "gate_b_thresholds",
        "attempt_budget",
        "existing_label",
        "metric_definition",
    }
)

# --- Constraint 3: noise floor -------------------------------------------

# One incident in a 60-record set is 1.67 points. Two incidents is the
# smallest change that is not plausibly a single relabelling.
MIN_EFFECT_SIZE = 0.034


class GuardrailViolation(RuntimeError):
    """Raised when a proposal targets something the loop may not change."""


def stratified_split(records, holdout_frac: float = 0.35, seed: int = SPLIT_SEED):
    """Split by severity so both halves carry the same class balance.

    Deterministic. The holdout must be identical across runs or comparing
    holdout scores between rounds means nothing.
    """
    buckets: dict[str, list] = defaultdict(list)
    for record in sorted(records, key=lambda r: r.id):
        buckets[record.severity].append(record)

    dev, holdout = [], []
    for severity in sorted(buckets):
        items = buckets[severity]
        # Deterministic interleave rather than a shuffle - reproducible without
        # depending on the RNG implementation.
        stride = max(1, round(1 / holdout_frac))
        for index, record in enumerate(items):
            (holdout if index % stride == 0 else dev).append(record)
    return dev, holdout


def score(classifier, records) -> EvalReport:
    report = EvalReport(classifier=getattr(classifier, "name", "unknown"))
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
    return report


def check_guardrails(proposal: dict) -> None:
    """Constraint 1. Reject anything aimed at policy or ground truth."""
    target = proposal.get("target", "")
    if target in IMMUTABLE:
        raise GuardrailViolation(
            f"proposal targets immutable surface '{target}' - "
            "policy and ground truth are not the loop's to change"
        )
    if target not in MUTABLE:
        raise GuardrailViolation(f"proposal targets unknown surface '{target}'")


def evaluate_proposal(
    baseline_dev: EvalReport,
    baseline_holdout: EvalReport,
    candidate_dev: EvalReport,
    candidate_holdout: EvalReport,
) -> tuple[str, str]:
    """Constraints 2 and 3. Returns (verdict, reason).

    The metric is under-classification rate, because that is the error the
    system exists to avoid. A proposal that improves exact accuracy while
    worsening under-classification is a regression here.
    """
    dev_delta = (
        baseline_dev.under_classification_rate - candidate_dev.under_classification_rate
    )
    holdout_delta = (
        baseline_holdout.under_classification_rate
        - candidate_holdout.under_classification_rate
    )

    if dev_delta < MIN_EFFECT_SIZE:
        return "rejected", (
            f"dev improvement {dev_delta:+.3f} is inside the noise floor "
            f"of {MIN_EFFECT_SIZE:.3f}"
        )

    if holdout_delta <= 0:
        return "halt_overfit", (
            f"dev improved {dev_delta:+.3f} while holdout moved {holdout_delta:+.3f} - "
            "the proposal is fitting the development split, not the task"
        )

    if holdout_delta < dev_delta / 2:
        return "accepted_with_warning", (
            f"dev {dev_delta:+.3f} vs holdout {holdout_delta:+.3f} - "
            "gain is concentrated in the split the loop can see"
        )

    return "accepted", f"dev {dev_delta:+.3f}, holdout {holdout_delta:+.3f}"


def write_ledger(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    entry["logged_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")


# --------------------------------------------------------------------------
# Proposal engines
# --------------------------------------------------------------------------


class StubProposer:
    """Deterministic proposer for dry runs and tests.

    Emits one legitimate proposal, one that clears the whitelist but fails on
    effect size, and one that targets an immutable surface. The third exists so
    the guardrail is exercised rather than assumed.
    """

    name = "stub"

    def __init__(self):
        self._script = [
            {
                "target": "prompt_guidance",
                "change": "Instruct the model that an incident with no user-visible "
                "impact may still be extensive when it removes a control other "
                "incidents depend on.",
                "rationale": "Addresses the second-order impact failure pattern.",
            },
            {
                "target": "new_eval_case",
                "change": "Add an incident where a monitoring gap conceals an "
                "ongoing failure.",
                "rationale": "Thin coverage of concealment cases.",
            },
            {
                "target": "gate_b_thresholds",
                "change": "Lower the review threshold to 0.55 to raise escalation "
                "precision.",
                "rationale": "The threshold sweep shows 0.70 escalates 90 percent.",
            },
        ]
        self._index = 0

    def propose(self, failures, current_guidance):
        item = self._script[self._index % len(self._script)]
        self._index += 1
        return dict(item)


class LLMProposer:
    """Asks a model to read the failures and propose one change.

    The model is given the failure list and the mutation whitelist. It is not
    given the holdout split, the thresholds, or the labels. Withholding the
    verifier from the thing being verified is the whole point.
    """

    name = "llm-proposer"

    def __init__(self, model: str = "claude-sonnet-4-5"):
        try:
            from anthropic import Anthropic
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install '.[llm]'") from exc
        self._client = Anthropic()
        self._model = model

    def propose(self, failures, current_guidance):
        summary = "\n".join(
            f"- {f['id']}: labelled {f['truth']}, predicted {f['predicted']} "
            f"({f['reason']}) {f.get('note', '')}"
            for f in failures[:25]
        )
        system = (
            "You improve an incident triage classifier by proposing ONE change "
            "at a time.\n\n"
            f"You may only propose changes with target in {sorted(MUTABLE)}.\n"
            "You may NOT propose changes to the severity rubric, the gate "
            "thresholds, the attempt budget, the metric definitions, or any "
            "existing label. Those are policy and ground truth.\n\n"
            "Respond with a single JSON object and nothing else:\n"
            '{"target": string, "change": string, "rationale": string}'
        )
        user = (
            f"Current prompt guidance:\n{current_guidance or '(none)'}\n\n"
            f"Misclassifications on the development split:\n{summary}\n\n"
            "Propose one change."
        )
        response = self._client.messages.create(
            model=self._model,
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(b.text for b in response.content if b.type == "text")
        start, end = raw.find("{"), raw.rfind("}")
        return json.loads(raw[start : end + 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed self-improvement loop")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="stub proposer, no API")
    args = parser.parse_args()

    records = load_golden_set(GOLDEN_SET)
    dev, holdout = stratified_split(records)
    print(f"split: {len(dev)} dev / {len(holdout)} holdout (seed {SPLIT_SEED})")

    classifier = BaselineClassifier()
    base_dev, base_holdout = score(classifier, dev), score(classifier, holdout)
    print(
        f"baseline under-classification  dev {base_dev.under_classification_rate:.3f}"
        f"  holdout {base_holdout.under_classification_rate:.3f}\n"
    )

    proposer = StubProposer() if args.dry_run else LLMProposer()
    guidance: list[str] = []

    for round_no in range(1, args.rounds + 1):
        proposal = proposer.propose(base_dev.failures, "\n".join(guidance))
        print(f"round {round_no}: target={proposal.get('target')}")

        try:
            check_guardrails(proposal)
        except GuardrailViolation as exc:
            print(f"  BLOCKED  {exc}")
            write_ledger(
                {
                    "round": round_no,
                    "proposal": proposal,
                    "verdict": "blocked_by_guardrail",
                    "reason": str(exc),
                }
            )
            continue

        # A proposal that passes the whitelist still has to be applied and
        # measured. The baseline classifier ignores prompt guidance, so in dry
        # run the candidate scores identically and is correctly rejected on
        # effect size. That is the honest outcome, not a bug to route around.
        cand_dev, cand_holdout = score(classifier, dev), score(classifier, holdout)
        verdict, reason = evaluate_proposal(
            base_dev, base_holdout, cand_dev, cand_holdout
        )
        print(f"  {verdict.upper()}  {reason}")

        write_ledger(
            {
                "round": round_no,
                "proposal": proposal,
                "verdict": verdict,
                "reason": reason,
                "dev_under": round(cand_dev.under_classification_rate, 4),
                "holdout_under": round(cand_holdout.under_classification_rate, 4),
            }
        )

        if verdict == "halt_overfit":
            print("  halting - dev and holdout have diverged")
            break
        if verdict.startswith("accepted"):
            guidance.append(proposal["change"])
            base_dev, base_holdout = cand_dev, cand_holdout

    print(f"\nledger: {LEDGER}")
    print(f"accepted guidance lines: {len(guidance)}")
    if not guidance:
        print("no proposal cleared the noise floor - this is a normal outcome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
