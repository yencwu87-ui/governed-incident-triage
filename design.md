# Design

## The problem this is actually solving

Incident triage is a good test case for governed AI because the decision is
consequential, the ground truth is contestable, and the cost of the two error
directions is wildly asymmetric. Calling a SEV1 a SEV3 forfeits a response
window and possibly a regulatory notification window. Calling a SEV3 a SEV1
wakes people up unnecessarily. Systems that report a single accuracy figure
are hiding this asymmetry.

## Severity is derived, not predicted

The classifier assesses **impact** and **urgency**. It never outputs a
severity. Severity is computed by `rubric.derive_severity()`.

This removes an entire error class. A model asked for a severity directly can
produce one that contradicts its own stated reasoning, and you cannot tell
from the output whether the reasoning or the label is wrong. By constraining
the model to the two inputs and deriving the output, any disagreement is
located precisely in the impact or urgency assessment, which is where a human
reviewer can actually engage with it.

It also means the rubric can be changed without retraining, re-prompting, or
re-validating the model. The severity matrix is a policy artifact and it lives
in a file that a risk function can read.

## Pydantic validates shape, not correctness

`TriageDecision` guarantees that a classification is well-formed - the enums
are real values, the confidence is in range, the rationale exists and is long
enough to be a rationale rather than a token.

It guarantees nothing about whether the classification is right. A perfectly
schema-valid decision can be badly wrong, and this distinction matters because
teams routinely present schema validation as though it were quality
assurance. Structural validity is a precondition for evaluation, not a
substitute for it.

Correctness is assessed in two separate places. Internal coherence is checked
by Gate A against the rubric. External correctness is measured by the eval
suite against labelled ground truth. Neither is Pydantic's job.

## Gate A and Gate B are different controls

This is the central claim of the project.

**Gate A - machine safety.** Deterministic and answer-agnostic. Every check it
performs is decidable without knowing the correct classification.

- Is the severity consistent with the stated impact and urgency?
- Is confidence above the floor at which the output is meaningfully a guess?
- Does the rationale contain identifiers that should not be written to a
  ticket?
- Has the model echoed an instruction embedded in the incident text?

A Gate A failure means the output is unsafe to emit at all. It is not a
quality judgement, and it is fully automatable precisely because it never
needs to know the right answer.

**Gate B - human accountability.** Asks who is answerable for the decision and
whether they must see it before it takes effect. Gate B is not a confidence
check dressed up in governance language. Its primary trigger is consequence.

The failure mode this design exists to prevent is the common pattern where a
system escalates on low confidence and auto-actions on high confidence. Under
that pattern, the most consequential decisions receive the *least* human
attention, because a confident SEV1 sails through while an uncertain SEV4 gets
reviewed. Certainty is not authority. A SEV1 goes to a human whether the model
is at 0.5 or 0.99.

Low confidence is retained as a Gate B trigger, but it is one trigger among
several rather than the organising principle.

Every escalation names its trigger. An escalation with no stated reason cannot
be audited, cannot be tuned, and gives the reviewer nothing to act on.

## The loop is bounded, and the bound is a control

`agent.py` implements reason - act - observe - reflect, capped at two
attempts.

The cap is a governance property rather than a cost control. An agent allowed
to retry indefinitely against a validator will eventually satisfy the
validator, and what it has satisfied is the validator - not the underlying
requirement. Two attempts, then the decision goes to a human with its
violations attached rather than being retried into compliance.

Reflection is fed Gate A violations only. Gate B triggers are deliberately
withheld from the model. Telling a classifier that a human is about to review
its answer changes the answer, and the change is not an improvement - it is
the model optimising against the reviewer.

## The baseline exists to make the LLM prove itself

A keyword classifier with no model and no network runs the same contract. If
an LLM cannot beat it by a margin that justifies the cost, the latency, and
the governance overhead, that is a finding worth publishing rather than
burying.

The baseline currently fails the governance thresholds. That is the documented
result, and it is the argument for using a model here at all. A test asserts
that it *continues* to fail, so that if a future change makes the keyword
approach adequate, someone has to notice.

## Metrics are chosen for the asymmetry

- **Under-classification rate** is the headline and the CI gate. It counts
  every incident called less severe than it was.
- **Within-one accuracy** matters because a system that is consistently one
  level conservative is operationally usable, while one that scatters is not.
- **Escalation recall** measures whether incidents that should have reached a
  human did, independently of whether the severity itself was right. A system
  can get severity wrong and still route correctly, and that is a materially
  better failure than the reverse.
- **Escalation precision** is tracked but not gated. Over-escalation is a cost,
  not a safety failure, and gating it would create pressure in exactly the
  wrong direction.

## Known limitations

- The golden set is synthetic and small at 60 records. It is sufficient to
  detect gross regression and to demonstrate the method. It is not sufficient
  to certify a production system.
- The baseline vocabulary was authored while looking at the golden set, so its
  scores are optimistic. This is stated in the module docstring as well.
- Ground truth labels encode one defensible reading of each incident.
  Reasonable practitioners would disagree on several, particularly the
  second-order cases such as INC-036 and INC-054 where nothing is broken until
  something else breaks.
- There is no drift detection, no cost tracking, and no A/B harness for prompt
  changes. These are the obvious next pieces of work.
