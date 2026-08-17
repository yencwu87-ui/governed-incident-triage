# Usefulness

Accuracy asks whether the classifier is right. Usefulness asks whether anyone
should run it. Those are different questions and the second is rarely asked,
because the answer is often no.

The honest benchmark is not another classifier. It is the policy the system
replaces — a human reads every ticket. That policy has perfect escalation
recall and zero automation. Anything claiming to be useful must buy meaningful
review-burden reduction at an acceptable cost in missed escalations.

    python evals/usefulness.py

---

## 1. Null-policy comparison

| Policy | Review burden | Effort saved | Dangerous misses | Safe automation |
| --- | --- | --- | --- | --- |
| always-SEV1 (escalate all) | 100.0% | 0.0% | 0 (0.0%) | 0 |
| always-SEV4 (escalate none) | 0.0% | 100.0% | 29 (100%) | 11 |
| always-SEV3 (modal guess) | 0.0% | 100.0% | 29 (100%) | 20 |
| random severity | 51.7% | 48.3% | 16 (55.2%) | 9 |
| **baseline-keyword-v2** | **90.0%** | **10.0%** | **2 (6.9%)** | **4** |
| perfect oracle | 58.3% | 41.7% | 0 (0.0%) | 25 |
| oracle at 33% error, uncalibrated | 60.0% | 40.0% | 1 (3.4%) | 21 |

A *dangerous miss* is a SEV1 or SEV2 auto-emitted with no human involved.

### The finding

**The keyword baseline is not useful.** It saves 10% of review effort. A human
still reads 54 of 60 tickets, and for that they get two dangerous misses. The
labour saved does not plausibly cover the cost of running, maintaining, and
governing the system. The correct engineering decision for this classifier
alone is to delete it and keep the human.

**The architecture is useful.** A perfect classifier through the same two gates
saves 41.7% of review effort with zero dangerous misses, and a classifier
degraded to a 33% error rate with no calibration help still saves 40.0% with
one. That gap — 10% versus 40% — is entirely attributable to classifier
quality, not to the gate design.

So the answer to "is this useful" splits. The pipeline is worth building. The
keyword classifier is not worth running through it.

Note also that random severity assignment saves 48.3% of effort — more than the
perfect oracle. Effort saved is meaningless on its own. It is only interpretable
against the dangerous-miss column, where random sits at 55.2% and the oracle at
zero. Any vendor quoting an automation rate without a paired safety number is
quoting the random policy's best feature.

---

## 2. Gate ablation

| Measure | Value |
| --- | --- |
| Consequential incidents in set | 29 |
| Reaching a human with Gate B | 27 (93.1%) |
| Reaching a human without Gate B | 0 |
| Unreviewed if the pipeline were ungated | 29 |
| Gate A blocks (baseline classifier) | 0 |
| Gate B escalations | 54 |

Gate B is carrying the safety property. Without it nothing routes to a human at
all, and 29 consequential incidents would land in a downstream system
unreviewed.

**Gate A blocked nothing.** That is the honest result and it is not a
disappointment. The baseline is rubric-coherent by construction, so there is
nothing for a coherence check to catch. Gate A's value showed up exactly once
in this project's history, when an integration failure with a reasoning model
caused every response to fail parsing — and Gate A turned 60 malformed outputs
into 60 clean blocks rather than 60 corrupt records or a stack trace.

Gate A is insurance, not a performance feature. Its expected value is zero on a
well-behaved classifier and total on a broken one. Measuring it on a good day
will always understate it.

---

## 3. Coverage sensitivity

What happens to the headline metric as the classifier refuses to answer?

| Refusal rate | Scored | Blocked | Under-classification | Within one | Escalation recall |
| --- | --- | --- | --- | --- | --- |
| 0% | 60 | 0 | **0.333** (fail) | 0.933 | 0.914 |
| 25% | 57 | 3 | 0.333 (fail) | 0.930 | 0.857 |
| 50% | 48 | 12 | 0.250 (fail) | 0.917 | 0.657 |
| 75% | 24 | 36 | **0.117 (pass)** | 0.917 | 0.429 |
| 100% | 0 | 60 | **0.000 (pass)** | 0.000 | 0.000 |

### The finding

**Refusing to answer is the optimal strategy for the headline metric.** A
blocked incident increments the denominator of under-classification but can
never increment the numerator, because a decision that does not exist cannot be
under-classified.

A classifier that declines 75% of its work takes under-classification from
33.3% — a clear failure — to 11.7%, a comfortable pass. Total refusal scores a
perfect zero.

This was found by accident. A real integration failure with qwen3.8 produced
60 blocked incidents and a scorecard reading 0.0% under-classification, which
is the best possible result on the metric the CI gate enforced.

What caught it was escalation recall and within-one accuracy — two thresholds
added almost as afterthoughts. The primary metric was silent.

### The fix

`min_scored_fraction: 0.90` is now a threshold in `run_evals.py`. A run that
cannot produce decisions for 90% of the corpus fails on its own terms rather
than relying on secondary metrics to notice.

The general lesson is worth stating beyond this project. **Any single safety
metric that improves when the system does less will eventually be satisfied by
the system doing nothing.** Under-classification rate has that shape.
Escalation precision has it in the opposite direction, which is why
`docs/backtest.md` records it but declines to gate on it. Coverage is the
paired metric that closes the gap, and it was missing from the original design.

---

## What this changes

The README leads with accuracy. It should not. On these numbers the honest
summary of the keyword baseline is that it does not earn its place, and the
honest summary of the design is that it has roughly 40 points of review-burden
reduction available to a classifier good enough to reach it.

That is a more useful thing to publish than an accuracy figure, and a more
uncomfortable one.
