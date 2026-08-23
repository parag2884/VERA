"""Permanent buckets. Every KnowledgeOps feature must land in one.

Observe  — detect, measure, compare, flag
Maintain — refresh metrics, contradiction edges, hygiene, health
Govern   — accept, reject, promote, rollback, lock, change policy (human only)
"""

from __future__ import annotations

OBSERVE = "observe"
MAINTAIN = "maintain"
GOVERN = "govern"

BUCKETS = {
    OBSERVE: {
        "label": "Observe",
        "may": ["Detect", "Measure", "Compare", "Flag"],
        "examples": ["debt", "drift", "coverage drop", "404 source watch"],
    },
    MAINTAIN: {
        "label": "Maintain",
        "may": ["Refresh metrics", "Contradiction edges", "Hygiene reports", "Health"],
        "examples": ["night care window", "weak-edge scan"],
    },
    GOVERN: {
        "label": "Govern",
        "may": ["Accept", "Reject", "Promote", "Rollback", "Lock", "Change policy"],
        "examples": ["draft goldens", "version promote", "rel locks"],
        "human_only": True,
    },
}

# Features Care is allowed to run without a person.
CARE_OBSERVE = frozenset({"hygiene_scan", "health_flags", "drift_flags", "source_watch"})
CARE_MAINTAIN = frozenset({"conflict_edges", "metric_snapshot", "entity_summaries"})
CARE_GOVERN = frozenset(
    {
        "accept_drafts",
        "reject_drafts",
        "promote_versions",
        "rollback_versions",
        "policy_locks",
        "ingest_knowledge",
        "rewrite_hierarchy",
        "rewrite_locked_facts",
    }
)


def classify(feature: str) -> str:
    if feature in CARE_GOVERN:
        return GOVERN
    if feature in CARE_MAINTAIN:
        return MAINTAIN
    return OBSERVE


def public_card() -> dict:
    return {
        "observe": BUCKETS[OBSERVE],
        "maintain": BUCKETS[MAINTAIN],
        "govern": BUCKETS[GOVERN],
        "rule": "Care can observe and maintain. Care cannot govern.",
    }
