# Synthetic data and the non-LLM comparison

Two questions this answers. Where does training data come from when you have no
incident records, and does this task actually need a language model?

    python evals/generate_incidents.py --count 3000
    python evals/run_evals.py --classifier gbdt --no-gate

---

## Why a gradient-boosted model at all

Model risk review reasonably asks why a task needs a language model, and
"because we didn't try anything else" is not an answer. Until now the only
non-LLM comparison in this project was a keyword matcher written by hand, which
nobody would mistake for a serious alternative.

TF-IDF features into gradient-boosted trees is the conventional answer. One head
for impact, one for urgency, severity derived from the rubric exactly as
everywhere else. Same contract, same gates, same metrics.

Unlike the LLM, it has to be trained. That requirement is itself the finding.

---

## The generator

`evals/generate_incidents.py` composes incidents from a system, a fault, a scope
phrase that fixes impact, and a time-pressure phrase that fixes urgency. Labels
are derived from the rubric, so they cannot contradict the matrix.

Roughly 45% are marked *hard* — scope stated as a number to be read as a
proportion rather than a phrase to be matched, or consequence placed outside the
sentence describing the fault. Confounders add alarming or regulatory vocabulary
that does not change severity.

**This does not make synthetic data a substitute for real data.** Anything a
template generator produces, a bag-of-words model can learn, because the scope
and urgency phrases are the label in light disguise. The `hard_fraction`
parameter narrows the gap. It does not close it, and the next section is what
that looks like measured.

---

## The result

Trained on 2,500 synthetic incidents. Tested twice.

| | Synthetic holdout (same distribution) | Hand-written golden set |
| --- | --- | --- |
| Exact severity accuracy | **99.8%** | **37.9%** |
| Within one level | 100.0% | 70.7% |
| Under-classification | 0.2% | 23.3% |
| Escalation recall | 100.0% | 97.1% |

A 62-point generalisation gap.

Three things follow, and all three are worth more than an accuracy number.

**Synthetic-only validation is not validation.** A model scoring 99.8% on
held-out data from its own generator has demonstrated that it learned the
generator. Any evaluation report quoting a single held-out figure without
stating the provenance of the holdout is uninterpretable. This is the whole
argument, in one table, on a system small enough to audit.

**The task needs a language model.** On human-written incidents the
gradient-boosted model reaches 37.9%, which is worse than the hand-written
keyword baseline at 58.3% and far behind llama3.1:8b at 66.7%. It also fails the
under-classification gate at 23.3%. The conventional alternative was tried and it
lost.

**The cost asymmetry is the practical argument.** The gradient-boosted model
needed 2,500 labelled examples and a training step. The LLM needed a prompt and
zero labelled examples. In a domain where labelled incident data is scarce,
confidential, or both, that difference decides the question before accuracy is
even considered.

### A detail worth noticing

The model over-classified 25 of 60 while under-classifying 14. It is
systematically alarmist on unfamiliar text, which is the safer direction to fail
in — reflected in escalation recall of 97.1%, the highest of any classifier
tested. A model that shouts about everything catches everything. It is also
close to useless, for the reasons `docs/usefulness.md` sets out about the
escalate-everything policy.

Gate A blocked one incident on the confidence floor. Since confidence here is a
product of two predicted probabilities rather than a self-report, it is better
calibrated than an LLM's stated confidence — which makes the Gate B comparison
across classifiers slightly unfair in the gradient-boosted model's favour.

---

## Where real data would come from

Synthetic data closes the training-data gap. It does not close the validation
gap, and nothing above should be read as suggesting otherwise.

For validation, published post-incident reviews are real incidents, publicly
available, and carry no confidentiality problem — cloud and platform providers
publish detailed postmortems continuously. Hand-labelling fifty of those against
this rubric would produce a validation set with genuine provenance, and the
gradient-boosted model's 37.9% suggests the result would be sobering for
everything in this repository, not just for it.

That is the next piece of work, and it is more valuable than any further
modelling.
