# Governed Incident Triage

An LLM incident triage classifier shipped with the two things such systems are
usually missing — an evaluation harness that runs on every commit, and an
explicit model of who is accountable for the output.

The interesting part is not the classifier. It is the separation of **machine
safety** from **human accountability** into two distinct gates, and the
argument that collapsing them into a single "human in the loop" control
produces a system where the most consequential decisions receive the least
human attention.

---

## The two gates

**Gate A — machine safety.** Deterministic. Asks whether the output is safe to
emit at all. Every check is decidable without knowing the correct answer, which
is exactly why it can be fully automated.

- severity consistent with the stated impact and urgency
- confidence above the floor at which the output is meaningfully a guess
- no identifiers written into free-text fields
- no instruction from the incident text echoed back by the model

**Gate B — human accountability.** Asks who is answerable and whether they must
see the decision before it takes effect. Its primary trigger is **consequence,
not confidence**.

A system that escalates on low confidence and auto-actions on high confidence
has it backwards — a confident SEV1 sails through while an uncertain SEV4 gets
reviewed. Here a SEV1 reaches a named human whether the model is at 0.5 or
0.99. Certainty is not authority.

Every escalation names its trigger and the accountable role. An escalation with
no stated reason cannot be audited.

## Severity is derived, not predicted

The classifier assesses **impact** and **urgency** only. Severity is computed
from the rubric matrix.

This removes an entire error class — a model cannot produce a severity that
contradicts its own reasoning — and it means the rubric is a policy artifact
that a risk function can read and change without touching the model.

---

## Results

Baseline, 60 synthetic incidents, regenerated on every commit:

| Metric | baseline-keyword-v2 |
| --- | --- |
| Exact severity accuracy | 58.3% |
| Within one level | 93.3% |
| **Under-classification rate** | **33.3%** |
| Escalation recall (Gate B) | 91.4% |
| Escalation precision (Gate B) | 59.3% |
| Blocked by Gate A | 0 |

**The baseline fails the governance gate.** Under-classification of 33.3%
against a 20% ceiling is the documented finding, and it is the argument for
using a model here at all. A test asserts that it *continues* to fail, so that
if a keyword approach ever becomes adequate, someone has to notice.

Under-classification is the headline rather than accuracy because the two error
directions are not equally costly. Calling a SEV1 a SEV3 forfeits a response
window. Calling a SEV3 a SEV1 wastes people's time. Confusion matrix and
per-class figures are in `evals/results/`.

---

## Quick start

```bash
git clone https://github.com/<your-username>/governed-incident-triage.git
cd governed-incident-triage
pip install -e ".[dev]"

pytest -q                                    # 50 tests, no API key needed
python evals/run_evals.py --no-gate          # baseline eval
```

Triage a single incident:

```bash
triage "the payment gateway is down at all branches, no workaround"
```

```
status    escalated
severity  SEV1  (extensive x critical)
category  availability
confidence 0.62
gate B    accountable: Incident Commander
          - consequence_threshold: SEV1
          - low_confidence: 0.62 < 0.70
          - notification_window_risk
```

To run the LLM classifier:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
python evals/run_evals.py --classifier llm
```

---

## Layout

```
src/triage/
  schemas.py        Pydantic contracts — shape, not correctness
  rubric.py         impact x urgency matrix, anchored on public standards
  gates.py          Gate A and Gate B
  agent.py          bounded reason-act-observe-reflect loop
  harness.py        batch runner
  classifiers/      keyword baseline and LLM, one shared contract
evals/
  data/golden_set.jsonl   60 labelled synthetic incidents
  metrics.py              asymmetric error and escalation metrics
  run_evals.py            runner with CI-enforceable thresholds
docs/
  design.md               why it is built this way
  rubric_provenance.md    where the rubric came from, and what is absent
  governance.md           control mapping and honest limitations
```

## Design notes worth reading

- [`docs/design.md`](docs/design.md) — why severity is derived, why Pydantic
  validates shape but not correctness, why the agent loop is capped at two
  attempts, and why reflection is fed Gate A violations but never Gate B
  triggers.
- [`docs/governance.md`](docs/governance.md) — control mapping, and a section
  on what this explicitly does *not* claim.
- [`docs/rubric_provenance.md`](docs/rubric_provenance.md) — the rubric derives
  from ITIL 4 and NIST SP 800-61. All incident data is synthetic. No
  organisation-specific taxonomy, threshold, or incident record appears
  anywhere in this repository.

## Limitations

The golden set is synthetic and small. The baseline vocabulary was authored
against it, so its scores are optimistic. Labels encode one defensible reading
of each incident and reasonable practitioners would disagree on several. There
is no drift detection and no independent review. This is a demonstration of
method, not a validated system — `docs/governance.md` says so at greater
length, because a governance artifact that overstates its own assurance is
worse than none.

## Licence

MIT. See [LICENSE](LICENSE).
