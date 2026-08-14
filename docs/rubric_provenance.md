# Rubric and data provenance

## Why this document exists

An incident severity rubric is one of the more sensitive artifacts an
organisation holds. It encodes what the business considers material, where its
escalation thresholds sit, and by implication where its regulatory reporting
lines fall. Publishing one from a prior employer would be a confidentiality
breach regardless of how the code around it was written.

Everything in this repository was constructed from public sources. This
document records how, so that the claim is checkable rather than asserted.

## Rubric anchoring

The impact and urgency dimensions and the derivation of priority from their
intersection follow the incident management practice described in **ITIL 4**,
which is public and widely taught. The specific four-by-four matrix in
`rubric.py` is a conventional rendering of that practice, not a reproduction of
any organisation's matrix.

The framing of impact along breadth of effect, and of urgency along
time-to-intolerable-consequence, is consistent with the incident
characterisation approach in **NIST SP 800-61** (Computer Security Incident
Handling Guide), which separates functional impact, information impact and
recoverability. The rubric here collapses those into a simpler two-axis model
suitable for general IT incidents rather than security incidents specifically.

The observation that some incident categories carry notification consequences
- and that under-classification in those categories is therefore
asymmetrically costly - reflects the general shape of incident notification
obligations in regulated sectors, including the technology risk management
expectations published by the **Monetary Authority of Singapore**. No specific
notification threshold, deadline, or reporting trigger from any regulation is
encoded in this code, and none should be inferred. `NOTIFICATION_SENSITIVE` in
`rubric.py` marks categories as *worth a human's attention*, nothing more.

Any organisation adopting this would need to replace the matrix, the
thresholds, and the accountable-role mapping with its own. They are
illustrative defaults.

## What is deliberately absent

- No organisation-specific severity definitions, escalation paths, or
  on-call structures.
- No named systems, applications, vendors, or internal service catalogues.
- No real incident records, ticket text, or extracts from any incident
  management system.
- No regulatory notification deadlines or thresholds.
- No control identifiers from any proprietary control catalogue.

## The golden set

All 60 incidents in `evals/data/golden_set.jsonl` are synthetic. They were
written for this repository to exercise specific properties of the pipeline
and cover generic infrastructure situations - database replication, storage
capacity, certificate expiry, phishing, third-party outage - that appear in
introductory ITSM material anywhere in the world.

The set is deliberately weighted toward cases that are hard for surface
pattern matching:

- **Second-order impact.** INC-036 (SIEM ingestion stopped) and INC-054
  (credential vault unreachable) have no user-visible effect at all. Nothing is
  broken until something else breaks.
- **Destroyed recoverability.** INC-039 (backups silently failing for 11
  nights) presents as healthy until a restore is needed.
- **Historic event, present urgency.** INC-018 and INC-050 describe errors that
  already occurred, where the urgency comes from disclosure having happened
  rather than from an ongoing outage.
- **Alarming vocabulary, contained blast radius.** INC-042 (truncated tables in
  staging) reads far worse than it is.
- **Regulatory vocabulary, low genuine urgency.** INC-028 mentions a regulatory
  deadline that is nine days away with a manual workaround available.
- **Prompt injection.** INC-047 contains an instruction addressed to the
  classifier. The incident text is data. A classifier that follows it has
  failed a safety property, not a quality one.

Labels were assigned by applying the published matrix to a stated impact and
urgency, and every label is machine-checked for consistency with the matrix by
`tests/test_agent_and_data.py`. This means the labels cannot silently drift
from the rubric, though it does not make them objectively correct - see the
limitations section of `design.md`.

## Reproducing or replacing the set

The set is plain JSONL with one object per line. Replacing it with your own
data requires only that each record carries `id`, `text`, `category`,
`impact`, `urgency`, `severity`, `expects_human_review`, and an optional
`note`. The test suite will reject any record whose severity contradicts the
matrix, which is a useful property when hand-labelling at volume.
