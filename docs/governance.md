# Governance model

This document maps the code to the control expectations it is designed to
satisfy. It is written for a reviewer who wants to know where the
accountability sits, not for a developer who wants to know how it runs.

## Control surface

| Control intent | Where it lives | Evidence it produces |
| --- | --- | --- |
| Output conforms to a defined contract | `schemas.TriageDecision` | Validation error on any malformed output |
| Reasoning is internally coherent | `gates.gate_a` rubric check | Named violation on any impact/urgency/severity contradiction |
| System does not act on a guess | `gates.gate_a` confidence floor | Named violation below the floor |
| Sensitive data is not written to records | `gates.gate_a` pattern checks | Named violation on identifiers in free text |
| Input cannot redirect the system | `gates.gate_a` injection check, INC-047 | Eval result and a named violation |
| Consequential decisions reach a human | `gates.gate_b` | Trigger list and named accountable role on every escalation |
| Escalations are explainable | `GateBResult.triggers` | Every escalation carries its reason |
| Autonomy is bounded | `agent.MAX_ATTEMPTS` | Trace showing attempt count and exhaustion |
| Decisions are reconstructable | `TriageOutcome.trace` | Full reason/act/observe/reflect record per incident |
| Performance is measured before deployment | `evals/run_evals.py` | Versioned JSON and markdown report per run |
| Performance is measured after change | CI workflow | Report regenerated and retained on every commit |
| Degradation is detected | `THRESHOLDS` and regression tests | Non-zero exit on breach |

## Where accountability sits

The system does not make accountable decisions. It makes a proposal and
routes it.

- **Gate A blocks** produce no decision of record. The output never reaches a
  downstream consumer. The named violations go to whoever is operating the
  system.
- **Gate B escalations** produce a proposed classification that a named role
  must accept before it takes effect. `GateBResult.accountable_role` names that
  role. The model's confidence does not transfer accountability.
- **Auto-emitted decisions** are limited to low-consequence, high-confidence,
  non-sensitive cases. This is the only path where no human is in the loop, and
  it is deliberately the narrowest path.

The design position is that automation of the *assessment* is appropriate and
automation of the *accountability* is not. Gate B is the boundary between
them, and it is drawn on consequence rather than on model certainty.

## What this does not claim

- It is not a validated model under any model risk management standard. It has
  an evaluation harness, which is a precondition for validation, not
  validation itself.
- It has no independent review. A validation exercise would require a second
  party to challenge the rubric, the labels, and the thresholds.
- The thresholds in `run_evals.py` are illustrative and were set by judgement,
  not by calibration against an operational tolerance.
- There is no monitoring for drift once deployed, and no mechanism to detect
  that the incident population has shifted away from the evaluation set.
- The golden set is too small to support a statistical claim about production
  performance.

Stating these plainly is the point. A governance artifact that overstates its
own assurance is worse than none, because it transfers unearned confidence to
whoever reads it.

## Suggested next controls

In rough order of value:

1. **Held-out evaluation set** maintained by someone other than the author of
   the classifier, so the vocabulary and prompt cannot be tuned against it.
2. **Inter-rater agreement** on the labels. If two experienced practitioners
   disagree on 20 percent of the set, that is the real ceiling on measurable
   accuracy and every metric above should be read against it.
3. **Drift monitoring** comparing the live incident distribution against the
   evaluation distribution.
4. **Reviewer feedback capture** so that Gate B overrides become labelled data
   rather than being lost.
5. **Cost and latency tracking** per decision, so the LLM's margin over the
   baseline can be assessed against what it costs to obtain.
