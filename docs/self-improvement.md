# Self-improvement

A loop that reads its own failures and proposes changes. The interesting part
is not the loop — it is the three constraints that stop it becoming a machine
for producing confident nonsense.

    python evals/selfimprove.py --dry-run       # deterministic, no API key
    python evals/selfimprove.py --rounds 3      # requires ANTHROPIC_API_KEY

## The problem being designed around

`docs/design.md` argues that an agent allowed to retry against a validator
eventually satisfies the validator rather than the requirement, and caps the
inner loop at two attempts on that basis. A self-improvement loop is the same
pattern on a longer horizon. Widening the horizon does not fix the failure. It
makes it slower and harder to see.

Self-improvement works where the verifier is trustworthy. Here the verifier is
60 synthetic records, labelled by one person, with a noise floor of 1.7 points
per incident. That is not a trustworthy verifier. A loop optimising against it
would reliably produce a prompt that scores better on the golden set and worse
on reality, and nothing in the metrics would reveal it.

Three constraints follow. None of them is tunable.

## Constraint 1 — mutation whitelist

The loop may propose changes to two things.

- `prompt_guidance` — additional instruction given to the classifier
- `new_eval_case` — a candidate incident to add to the evaluation set

It may not touch the severity matrix, either gate's thresholds, the attempt
budget, the metric definitions, or any existing label. Those are policy and
ground truth.

A system permitted to move its own goalposts is not improving, it is drifting,
and from the inside the two are indistinguishable. The most seductive proposal
a loop can make is the one that lowers the bar, because it always works.

The stub proposer deliberately emits one immutable-target proposal so the
guardrail is exercised on every dry run rather than assumed. In the dry run it
proposes lowering the Gate B threshold to 0.55 — which is a *good idea*,
supported by the threshold sweep in `docs/backtest.md`, and it is still
blocked. That is the point. A well-reasoned change to a control surface is a
change a human signs off, not one a loop merges.

## Constraint 2 — holdout guard

The set is split 39 development / 21 holdout, stratified by severity, with a
fixed seed and a deterministic interleave rather than a shuffle. The holdout
must be byte-identical across runs or comparing holdout scores between rounds
means nothing.

Proposals are scored on dev. Holdout is scored only to detect divergence.

| Dev | Holdout | Verdict |
| --- | --- | --- |
| improves below the noise floor | — | rejected |
| improves | flat or worse | **halt, overfitting** |
| improves | improves by less than half as much | accepted with warning |
| improves | improves comparably | accepted |

The halt condition is the only mechanism here that can tell improvement from
memorisation. When it fires the loop stops rather than continuing, because a
loop that has started fitting the split will keep doing so and every subsequent
round makes the result harder to unpick.

The proposing model never sees the holdout, the thresholds, or the labels.
Withholding the verifier from the thing being verified is not a courtesy, it is
the mechanism.

## Constraint 3 — effect size floor

One incident in 60 moves the headline metric by 1.7 points. The floor is set at
3.4 points, which is two incidents — the smallest change not plausibly a single
relabelling.

Proposals below the floor are rejected as indistinguishable from chance. In the
dry run every legitimate proposal is rejected on exactly this basis, and the
run prints that no proposal cleared the floor and that this is a normal
outcome. A loop that always finds an improvement is a loop that is measuring
noise.

## The ledger

Every proposal is appended to `evals/results/improvement_ledger.jsonl` with its
target, its text, the verdict, the reason, and both split scores. Rejected and
blocked proposals are recorded as fully as accepted ones.

This is the governance artifact, not a debug log. A loop that improves a system
without leaving a record of what it changed and why has replaced a reviewable
process with an unreviewable one. Six months on, the ledger is the only thing
that can answer why the prompt says what it says.

## The metric it optimises

Under-classification rate, not accuracy. A proposal that improves exact
accuracy while worsening under-classification is a regression here, because
under-classification is the error the system exists to avoid.

This matters more than it sounds. Most optimisation loops default to whatever
metric is most readily available, and inherit that metric's blind spots
permanently.

## What this is not

- It does not train anything. No weights move. It proposes text.
- It cannot run unattended to convergence. Accepted proposals are guidance
  lines a human reads before they become part of the prompt.
- With 60 records it will almost never accept anything, which is correct
  behaviour at this sample size and the honest result to publish.
- Adding cases to the evaluation set via `new_eval_case` needs a human label.
  A loop that generates its own ground truth has closed the circle entirely.

## Where this becomes genuinely useful

At a few hundred records with inter-rater agreement established, the noise
floor drops and the holdout guard starts having real discriminating power. At
that point the loop is worth running. Below it, the loop's main value is the
ledger — it forces every proposed change to state its target, its reason, and
its measured effect before anyone acts on it.

Which is, arguably, the more transferable half of the idea.
