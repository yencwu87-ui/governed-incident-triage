"""Deterministic keyword baseline.

This exists so the LLM has something to beat, and so the eval suite can run in
CI with no API key. It reads surface vocabulary and has no notion of business
context, second-order consequence, or time-to-impact - which is precisely the
gap an LLM is supposed to close.

An honest caveat, stated here rather than buried: the vocabulary below was
authored while looking at the golden set. Its scores are therefore optimistic
and should be read as a floor, not as an independent benchmark. A genuinely
held-out baseline would score lower.
"""

from __future__ import annotations

import re

from ..rubric import derive_severity
from ..schemas import Category, Impact, TriageDecision, Urgency

_CATEGORY_TERMS: dict[Category, tuple[str, ...]] = {
    Category.SECURITY: (
        "breach", "ransomware", "malware", "phishing", "unauthorised",
        "unauthorized", "intrusion", "credential", "exfiltrat", "brute force",
        "privilege", "vulnerability", "exploit", "antivirus", "siem",
        "multi-factor", "world-readable", "unexpected domain", "access logs",
    ),
    Category.DATA_INTEGRITY: (
        "corrupt", "data loss", "mismatch", "reconcil", "duplicate",
        "truncat", "checksum", "replication lag", "stale data",
        "integrity", "double count", "same file twice", "backup job",
        "belonging to other",
    ),
    Category.THIRD_PARTY: (
        "vendor", "supplier", "third party", "third-party", "upstream",
        "saas", "managed service", "carrier", "provider", "outsourced",
        "status page", "corporate client", "telephony",
    ),
    Category.CAPACITY: (
        "disk space", "tablespace", "capacity", "quota", "storage",
        "memory exhaust", "connection pool", "thread pool", "licence limit",
        "license limit", "exhaust", "chiller", "ambient temperature",
        "percent and growing",
    ),
    Category.CHANGE: (
        "deployment", "release", "patch", "rollback", "rolled back",
        "configuration change", "change window", "upgrade", "migration",
        "driver update", "firewall rule change", "certificate renewal",
        "logon script",
    ),
    Category.PERFORMANCE: (
        "slow", "latency", "timeout", "response time", "backlog",
        "throughput", "degraded performance", "delayed", "tripled",
    ),
    Category.AVAILABILITY: (
        "outage", "unavailable", "is down", "cannot access", "unreachable",
        "failover", "crash", "not responding", "offline", "cannot log in",
        "halted", "failed to generate", "will not",
    ),
}

_IMPACT_TERMS: dict[Impact, tuple[str, ...]] = {
    Impact.EXTENSIVE: (
        "all users", "all customers", "all staff", "all branches", "all desks",
        "all sites", "all production", "any application", "every user",
        "enterprise-wide", "group-wide", "organisation-wide", "entire region",
        "whole organisation", "across the estate", "no user can",
        "any production system", "the estate", "all applications",
    ),
    Impact.SIGNIFICANT: (
        "multiple departments", "multiple sites", "multiple teams",
        "several hundred", "majority of", "large number", "many users",
        "several offices", "3,000", "roughly 400", "about 200",
        "80 contractors", "60 percent", "a third of", "multiple",
    ),
    Impact.MODERATE: (
        "one team", "single site", "one department", "a subset", "subset of",
        "some users", "one office", "small group", "two branches",
        "one branch", "one reporting team", "two linux hosts", "one instance",
    ),
    Impact.MINOR: (
        "one user", "single user", "an individual", "cosmetic",
        "one workstation", "single laptop", "one mailbox", "one meeting room",
        "purely cosmetic", "one server", "a widget", "one specific",
    ),
}

_URGENCY_TERMS: dict[Urgency, tuple[str, ...]] = {
    Urgency.CRITICAL: (
        "no workaround", "completely unavailable", "halted", "cannot transact",
        "cannot log in", "not clearing", "stopped processing", "total outage",
        "actively exploited", "still spreading", "not possible",
        "within the hour", "will begin failing", "unresolvable",
        "already been circulated", "were dispatched", "market is open",
        "cut-off is today", "rising fast", "no space to reclaim",
        "effectively blind", "are refused", "sat there", "cannot retrieve",
    ),
    Urgency.HIGH: (
        "deteriorating", "worsening", "backlog is growing", "and growing",
        "rising", "escalating", "intermittent failures", "degraded",
        "thin", "expires in", "not yet confirmed", "saturating",
        "consecutive nights", "increased tenfold", "have not updated",
        "pending investigation", "pending review",
    ),
    Urgency.MEDIUM: (
        "workaround", "manual process", "manually", "alternate",
        "fall back", "recoverable", "mirrored", "still complete",
        "can continue", "non-critical", "internal only", "restructure",
        "re-run", "resolves it", "retrospective", "underway",
    ),
    Urgency.LOW: (
        "cosmetic", "no service impact", "no user impact", "unaffected",
        "purely", "scheduled", "next week", "90 days", "nine days",
        "documentation", "typo", "values are correct", "walking",
        "nothing is failing", "if they have one",
    ),
}

# Phrases whose presence must suppress a weaker signal contained within them.
_NEGATIONS: tuple[str, ...] = ("no workaround", "not possible")


def _score(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if term in text)


def _best(text: str, mapping: dict, default):
    scores = {key: _score(text, terms) for key, terms in mapping.items()}
    top = max(scores.values())
    if top == 0:
        return default, 0
    for key in mapping:  # first key at top score, preserving declaration order
        if scores[key] == top:
            return key, top
    return default, 0


def _suppress(text: str) -> tuple[str, bool]:
    """Blank out negated phrases so a weaker substring cannot score on them."""
    found = False
    for phrase in _NEGATIONS:
        if phrase in text:
            text = text.replace(phrase, " ")
            found = True
    return text, found


class BaselineClassifier:
    """Keyword scoring over a fixed vocabulary. No model, no network."""

    name = "baseline-keyword-v2"

    def classify(
        self,
        incident_id: str,
        text: str,
        feedback: str | None = None,
    ) -> TriageDecision:
        normalised = re.sub(r"\s+", " ", text.lower())
        urgency_text, negated = _suppress(normalised)

        category, cat_hits = _best(normalised, _CATEGORY_TERMS, Category.AVAILABILITY)
        impact, imp_hits = _best(normalised, _IMPACT_TERMS, Impact.MODERATE)
        urgency, urg_hits = _best(urgency_text, _URGENCY_TERMS, Urgency.MEDIUM)

        # The negated phrase itself is a critical-urgency signal.
        if negated:
            urgency, urg_hits = Urgency.CRITICAL, max(urg_hits, 1)

        severity = derive_severity(impact, urgency)

        # Confidence reflects evidence found, not correctness. A zero-hit
        # classification is a fallback and says so.
        hits = min(cat_hits + imp_hits + urg_hits, 6)
        confidence = round(0.35 + 0.09 * hits, 2)

        indicators = [
            f"category_terms={cat_hits}",
            f"impact_terms={imp_hits}",
            f"urgency_terms={urg_hits}",
        ]

        rationale = (
            f"Keyword baseline matched {cat_hits} category term(s), "
            f"{imp_hits} impact term(s) and {urg_hits} urgency term(s). "
            f"Impact assessed as {impact.value} and urgency as {urgency.value}, "
            f"which the rubric derives to {severity.value}."
        )

        return TriageDecision(
            incident_id=incident_id,
            category=category,
            impact=impact,
            urgency=urgency,
            severity=severity,
            confidence=confidence,
            rationale=rationale,
            indicators=indicators,
        )
