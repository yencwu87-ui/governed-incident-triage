"""Synthetic incident generator.

Produces labelled incidents at a scale the hand-written golden set cannot
reach, so that a supervised model has something to train on.

The generator is compositional. An incident is a system, a fault, a scope
phrase that determines impact, and a time-pressure phrase that determines
urgency. Severity is then derived from the rubric, so labels cannot contradict
the matrix by construction.

A warning that belongs at the top rather than the bottom. **Anything a template
generator produces, a bag-of-words model can learn.** The scope and urgency
phrases are the label in lightly disguised form, so a supervised model trained
here will score highly on held-out synthetic data and that score will mean
almost nothing. The only informative test is the hand-written golden set, which
comes from a different distribution - a human wrote each one to be awkward.

The `hard_fraction` parameter exists to narrow that gap, not to close it. Hard
incidents express scope as a number to be interpreted rather than a phrase to
be matched, or place the consequence outside the sentence describing the fault.
They make the task harder. They do not make synthetic data a substitute for
real data.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from triage.rubric import derive_severity  # noqa: E402
from triage.schemas import Impact, Urgency  # noqa: E402

OUT = ROOT / "evals" / "data" / "synthetic_train.jsonl"
SEED = 20260817

SYSTEMS = {
    "availability": [
        "the customer portal", "the authentication service", "the branch teller system",
        "the mobile application",
        "the internal intranet",
        "the document management system",
        "the scheduling engine", "the service desk portal", "the reporting gateway",
    ],
    "security": [
        "the remote access gateway", "the privileged access vault", "the endpoint agent",
        "the mail filtering service",
        "the log ingestion pipeline",
        "the certificate authority",
    ],
    "data_integrity": [
        "the settlement reconciliation job",
        "the customer master feed",
        "the data warehouse load",
        "the replication link", "the nightly backup job", "the ledger export",
    ],
    "performance": [
        "the search index", "the pricing service", "the statement renderer",
        "the API gateway", "the batch scheduler",
    ],
    "third_party": [
        "the upstream payments provider",
        "the managed network carrier",
        "the SaaS expense platform",
        "the outsourced print vendor", "the market data feed",
    ],
    "capacity": [
        "the primary storage array",
        "the database connection pool",
        "the virtual desktop platform",
        "the message queue", "the archive tier",
    ],
    "change": [
        "last night's release", "the firewall rule change", "the platform upgrade",
        "the certificate rotation", "the schema migration",
    ],
}

FAULTS = {
    "availability": ["is unreachable",
    "has stopped responding",
    "is returning errors on every request"],
    "security": ["logged repeated unauthorised access attempts",
    "was found misconfigured",
                 "has an unpatched vulnerability", "recorded credential misuse"],
    "data_integrity": ["produced duplicate records", "wrote incomplete output",
                       "fell behind and is serving stale data",
                       "failed its checksum validation"],
    "performance": ["is responding four times slower than baseline",
    "is timing out intermittently",
                    "has accumulated a processing backlog"],
    "third_party": ["has declared a service degradation", "is rejecting our requests",
                    "notified us of an unplanned outage"],
    "capacity": ["is close to exhausting its allocation", "has refused new connections",
                 "reached its configured ceiling"],
    "change": ["introduced a regression", "was applied outside the approved window",
               "left the estate in an inconsistent state"],
}

# Scope phrases. Easy ones name the population. Hard ones state a number that
# has to be read as a proportion of something.
SCOPE_EASY = {
    Impact.EXTENSIVE: ["affecting all customers", "across the entire estate",
                       "for every user in every region", "enterprise-wide"],
    Impact.SIGNIFICANT: ["affecting multiple departments", "across several sites",
                         "for a large share of active users", "in two of five regions"],
    Impact.MODERATE: ["affecting one team", "at a single site",
                      "for one department", "in one branch"],
    Impact.MINOR: ["affecting one user", "for a single workstation",
                   "with no functional effect", "cosmetically only"],
}
SCOPE_HARD = {
    Impact.EXTENSIVE: ["Roughly 48,000 of our 50,000 accounts are affected",
                       "Every channel we operate routes through it",
                       "No alternative path exists anywhere in the estate"],
    Impact.SIGNIFICANT: ["Around 6,000 of 50,000 accounts are affected",
                         "Three of our eleven business lines depend on it",
                         "It underpins about a third of daily volume"],
    Impact.MODERATE: ["Around 300 of 50,000 accounts are affected",
                      "One downstream process consumes it",
                      "A single reporting team relies on the output"],
    Impact.MINOR: ["Two accounts are affected",
                   "One person has reported it",
                   "It changes only how a label is rendered"],
}

URGENCY_EASY = {
    Urgency.CRITICAL: ["There is no workaround and the business function has stopped.",
                       "Transactions cannot complete and the impact "
                       "compounds by the minute."],
    Urgency.HIGH: ["A partial workaround exists but the position is deteriorating.",
                   "The backlog is growing and manual effort is not keeping pace."],
    Urgency.MEDIUM: ["A workaround is in place and can be held through the working day.",
                     "Staff are using a manual process in the meantime."],
    Urgency.LOW: ["There is no time pressure and it can be scheduled normally.",
                  "Nothing is failing and the fix can wait for the next window."],
}
# Hard urgency puts the consequence outside the sentence describing the fault,
# or in the past with a live disclosure consequence.
URGENCY_HARD = {
    Urgency.CRITICAL: ["Nothing is broken yet, but every recovery path "
                       "for other incidents runs through it.",
                       "The error already reached external recipients before it was "
                       "noticed.",
                       "Monitoring for the whole estate is blind while this persists."],
    Urgency.HIGH: ["It has been failing silently for nine consecutive "
                   "nights and nobody noticed.",
                   "Capacity headroom is now thin enough that one more failure "
                   "would be visible.",
                   "The certificate behind it expires within two working days."],
    Urgency.MEDIUM: ["Output can be regenerated once the underlying job is corrected.",
                     "The affected records are recoverable from the previous run."],
    Urgency.LOW: ["The supplier has given ninety days' notice, and "
                  "migration is a six-week effort.",
                  "It is a documented risk rather than a live fault."],
}

# Confounders. Alarming or regulatory vocabulary that does not change severity.
CONFOUNDERS = [
    "", "", "", "",  # most incidents get none
    " The words breach and outage appear in the original ticket text.",
    " The reporter flagged it as urgent, though the assessment below governs.",
    " A regulatory return depends on this system later in the quarter.",
    " This was initially escalated as critical before triage.",
]


def generate(count: int, hard_fraction: float = 0.45, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    records = []
    categories = list(SYSTEMS)

    for index in range(count):
        category = rng.choice(categories)
        impact = rng.choice(list(Impact))
        urgency = rng.choice(list(Urgency))
        hard = rng.random() < hard_fraction

        system = rng.choice(SYSTEMS[category])
        fault = rng.choice(FAULTS[category])
        scope = rng.choice((SCOPE_HARD if hard else SCOPE_EASY)[impact])
        pressure = rng.choice((URGENCY_HARD if hard else URGENCY_EASY)[urgency])
        confounder = rng.choice(CONFOUNDERS)

        if hard:
            text = f"{system.capitalize()} {fault}. {scope}. {pressure}{confounder}"
        else:
            text = f"{system.capitalize()} {fault} {scope}. {pressure}{confounder}"

        severity = derive_severity(impact, urgency)
        records.append(
            {
                "id": f"SYN-{index + 1:05d}",
                "text": text,
                "category": category,
                "impact": impact.value,
                "urgency": urgency.value,
                "severity": severity.value,
                "expects_human_review": severity.value in ("SEV1", "SEV2")
                or category in ("security", "data_integrity"),
                "note": "hard" if hard else "easy",
            }
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate synthetic incidents")
    parser.add_argument("--count", type=int, default=3000)
    parser.add_argument("--hard-fraction", type=float, default=0.45)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    records = generate(args.count, args.hard_fraction, args.seed)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")

    from collections import Counter

    print(f"wrote {len(records)} incidents to {path}")
    print("severity:", dict(sorted(Counter(r["severity"] for r in records).items())))
    print("difficulty:", dict(Counter(r["note"] for r in records)))
    print(
        "\nThese are templates. A bag-of-words model will learn them. "
        "Test on the hand-written golden set, not on a synthetic holdout."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
