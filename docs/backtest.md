# Backtest

Three experiments the single eval run cannot answer. Everything here is
deterministic given the seed and runs with no API key.

    python evals/backtest.py

Raw output is written to `evals/results/backtest.json`.

---

## 1. Failure taxonomy

The baseline misses 25 of 60. The count is not the interesting part — the
question is what kind of incident it systematically cannot read.

| Pattern | Missed | Rate |
| --- | --- | --- |
| Historic event, present urgency | 4/4 | 100% |
| Prompt injection | 1/1 | 100% |
| Regulatory vocabulary, low genuine urgency | 2/3 | 67% |
| Second-order impact | 2/5 | 40% |
| Alarming words, contained blast radius | 1/3 | 33% |
| Scale stated numerically | 1/4 | 25% |

The pattern is coherent. Keyword matching fails wherever severity depends on
something **not present in the text as vocabulary** — a consequence that has
already occurred, a dependency that will bite later, a number that has to be
read as a proportion of a population. It succeeds where the words carry the
meaning directly.

Impact and urgency fail at similar rates (21 and 18 errors respectively), so
neither axis is carrying the failure alone.

### The result that matters

Of 20 under-classifications, **18 still reached a human** because Gate B fired
on another trigger — usually category or consequence. Only 2 were silent.

This is the design working as intended. The gate is not downstream of
classifier quality, so a wrong severity does not automatically become an
unreviewed decision.

The honest counterpoint, which belongs in the same paragraph: at the current
threshold the baseline escalates 90% of all incidents, with escalation
precision of 59%. Catching 18 of 20 errors is cheap when you are escalating
almost everything. The rescue rate and the escalation rate have to be read
together, and the next experiment separates them.

---

## 2. Degradation curve

A synthetic oracle starts from ground truth and corrupts it at a controlled
rate. This measures the **protective margin of the design** rather than the
quality of any model.

Three variants, because the difference between them is the finding.

| Variant | What it corrupts | Confidence behaviour |
| --- | --- | --- |
| Calibrated, severity only | impact or urgency, one level | drops to 0.55 when wrong |
| Calibrated, + category | also the category | drops to 0.55 when wrong |
| Overconfident, + category | also the category | stays at 0.88 always |

The first two variants hold escalation recall at 100% all the way to a 60%
error rate. That looks impressive and is close to meaningless — a perfectly
calibrated classifier lowers its confidence exactly when it is wrong, so the
low-confidence trigger catches every error by construction. The experiment is
measuring calibration, not the gate.

**The third variant is the real test.** With no calibration help, escalation
recall falls from 100% to a floor of about 94% and stays there across the whole
range. It never approaches the 85% threshold.

Escalation precision behaves in the opposite direction and is worth noting.
The overconfident oracle holds precision between 94% and 100%, while the
calibrated one degrades to 67%. The low-confidence trigger, when it fires
often, is a major source of over-escalation.

### Interpretation

Consequence-based escalation is robust to classifier quality in a way that
confidence-based escalation is not. The structural reason is that SEV1, SEV2,
and the sensitive categories cover a wide band of the corpus, and a one-level
misread rarely moves an incident out of that band entirely.

That is the central design claim of this project, and this is the evidence for
it.

### What this experiment does not show

- Perturbations are one level in either direction. A catastrophic misread —
  SEV1 read as SEV4 — is not modelled, and that is the failure that would
  actually defeat the gate.
- 58% of the golden set is escalation-worthy. On a corpus dominated by SEV3
  and SEV4 the band is narrower and the result would be weaker.
- 60 records means each point carries a few percentage points of noise. Read
  the shape, not the individual values.

---

## 3. Gate B threshold sweep

What does the confidence trigger actually buy? Re-run Gate B across the full
threshold range, holding the consequence and category triggers constant.

| Threshold | Escalation rate | Recall | Precision | Auto-emitted |
| --- | --- | --- | --- | --- |
| 0.00–0.40 | 51.7% | 82.9% | 93.5% | 23 |
| 0.50 | 60.0% | 85.7% | 83.3% | 19 |
| 0.60 | 75.0% | 88.6% | 68.9% | 11 |
| **0.70 (current)** | **90.0%** | **91.4%** | **59.3%** | **3** |
| 0.80 | 98.3% | 97.1% | 57.6% | 0 |
| 0.85+ | 100% | 100% | 58.3% | 0 |

Below 0.40 the trigger is inert — the baseline's confidence never drops that
low, so escalation is driven entirely by consequence and category. Above 0.80
it escalates everything and there is no automation left.

The current 0.70 sits in an awkward place. It escalates 90% of incidents to
buy 8.5 points of recall over the inert setting, and it drops precision from
94% to 59%. Full recall requires 0.85, which means auto-emitting nothing at
all.

### Finding

**With this classifier there is no useful middle setting.** The confidence
trigger is either doing nothing or doing everything. Consequence and category
are carrying the design, and they achieve 82.9% recall at 93.5% precision with
the confidence trigger switched off entirely.

That is an argument for lowering the threshold to around 0.50 and accepting
85.7% recall in exchange for a workable escalation rate — or for dropping the
confidence trigger and treating it as a diagnostic signal rather than a
control. Either is defensible. What is not defensible is leaving 0.70 in place
without knowing it escalates nine incidents in ten.

The threshold was originally set by judgement. This is what judgement bought.

---

## Caveats on all three

Synthetic data, 60 records, one author's labels, a baseline whose vocabulary
was written while looking at the evaluation set. These experiments demonstrate
a method for interrogating a governed classifier. They do not certify this
one. See `docs/governance.md` for the full limitations.
