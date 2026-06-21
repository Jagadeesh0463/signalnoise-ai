"""
src/signals/confidence.py

Confidence Engine — computes an explainable percentage confidence for each signal.

Replaces the coarse high/medium/low band with a precise integer score (50–97)
derived from multiple corroborating factors.

Design rules:
    - No ML models — purely structured, explainable computation
    - Score components are individually logged so the UI can show "why"
    - Returns both a score (int) and a breakdown (dict) for transparency
    - Never returns < 50 (something detected) or > 97 (we're never certain)

Usage:
    from src.signals.confidence import compute_confidence
    score, breakdown = compute_confidence(signal, evidence_list, total_docs=10)
"""

from __future__ import annotations

import logging

from src.models import Evidence, Signal

logger = logging.getLogger(__name__)

# Risk keywords — imported locally to avoid circular import with detector
_RISK_KEYWORDS = {
    "delayed", "delay", "blocked", "blocking", "overdue", "slipped",
    "missed", "behind", "critical", "escalate", "escalation", "risk",
    "blocker", "dependency", "deadline", "milestone", "pushed", "deferred",
    "velocity", "sprint", "capacity", "commitments", "rework",
    "burnout", "understaffed", "overwhelmed", "attrition", "overtime",
    "leaving", "resigned", "morale", "frustrated", "tired", "exhausted",
    "overloaded", "weekend", "hours", "allocation", "workload", "stress",
    "transfer", "resignation", "elsewhere", "headcount", "retention",
    "quit", "replace", "backfill",
    "sole", "single", "only", "knowledge", "understands", "bus",
    "silos", "silo", "documentation", "undocumented",
    "debt", "coverage", "tests", "testing", "qa", "quality", "bugs",
    "refactor", "legacy", "fragile", "flaky", "regression", "hotfix",
    "incident", "outage", "failure", "failing", "degraded", "alert",
    "rollback", "breach", "error", "crash", "broken",
    "unresolved", "pending", "waiting", "stuck", "ignored",
}

# Category certainty priors — dependency has precise vocabulary, delivery_risk is fuzzy
_CATEGORY_PRIOR: dict[str, float] = {
    "dependency":     0.95,
    "operational":    0.90,
    "technical_debt": 0.85,
    "attrition":      0.85,
    "bus_factor":     0.80,
    "team_health":    0.75,
    "delivery_risk":  0.65,
}


def compute_confidence(
    signal: Signal,
    evidence_list: list[Evidence] | None = None,
    total_docs: int = 1,
) -> tuple[int, dict[str, float]]:
    """
    Compute a confidence percentage and an explainability breakdown.

    Formula (weighted sum → mapped to [50, 97]):
        35% — document coverage  (how many docs mention this signal)
        25% — evidence quality   (snippet count + average relevance)
        20% — severity weight    (STRONG = 1.0, WEAK = 0.4)
        15% — keyword density    (risk keywords found in evidence text)
        5%  — category prior     (some categories have clearer vocabulary)

    Args:
        signal:        Signal object with severity, category, evidence, source_doc_ids.
        evidence_list: Validated Evidence objects from the validator.
        total_docs:    Total documents processed in this run (for coverage ratio).

    Returns:
        Tuple of (confidence_pct: int, breakdown: dict[str, float])
        breakdown contains each component score for display/logging.
    """
    evidence_list = evidence_list or []
    doc_ids = set(signal.source_document_ids) if signal.source_document_ids else set()
    doc_count = len(doc_ids)
    evidence_count = len(evidence_list)

    # ── Component 1: Document coverage (0–1) ──────────────────────────────────
    # Saturates at 8 docs — beyond that confidence gain is marginal
    doc_score = min(doc_count / max(min(total_docs, 8), 1), 1.0)

    # ── Component 2: Evidence quality (0–1) ──────────────────────────────────
    if evidence_list:
        avg_relevance = sum(e.relevance_score for e in evidence_list) / len(evidence_list)
        snippet_score = min(evidence_count / 5.0, 1.0)
        evidence_score = snippet_score * 0.6 + avg_relevance * 0.4
    else:
        # Fallback: use signal's embedded evidence snippets
        snippet_score = min(len(signal.evidence) / 5.0, 1.0)
        evidence_score = snippet_score * 0.4   # penalised — no formal validation

    # ── Component 3: Severity weight (0–1) ───────────────────────────────────
    severity_score = {"STRONG": 1.0, "WEAK": 0.4, "NOISE": 0.0}.get(signal.severity, 0.4)

    # ── Component 4: Keyword density (0–1) ───────────────────────────────────
    all_text = " ".join(signal.evidence).lower()
    if evidence_list:
        all_text += " " + " ".join(e.snippet.lower() for e in evidence_list)
    kw_hits = sum(1 for kw in _RISK_KEYWORDS if kw in all_text)
    keyword_score = min(kw_hits / 10.0, 1.0)

    # ── Component 5: Category prior (0–1) ────────────────────────────────────
    category_score = _CATEGORY_PRIOR.get(signal.category, 0.65)

    # ── Weighted sum → confidence percentage ─────────────────────────────────
    weighted = (
        0.35 * doc_score
        + 0.25 * evidence_score
        + 0.20 * severity_score
        + 0.15 * keyword_score
        + 0.05 * category_score
    )

    confidence_pct = int(50 + weighted * 47)
    confidence_pct = max(50, min(97, confidence_pct))

    breakdown = {
        "doc_coverage":     round(doc_score, 3),
        "evidence_quality": round(evidence_score, 3),
        "severity_weight":  round(severity_score, 3),
        "keyword_density":  round(keyword_score, 3),
        "category_prior":   round(category_score, 3),
        "weighted_sum":     round(weighted, 3),
    }

    logger.debug(
        "Confidence for signal=%s [%s]: %d%% — breakdown=%s",
        signal.id[:8],
        signal.category,
        confidence_pct,
        breakdown,
    )

    return confidence_pct, breakdown


def band_from_score(score: int) -> str:
    """Map a confidence percentage to a band label for legacy compatibility."""
    if score >= 85:
        return "high"
    if score >= 65:
        return "medium"
    return "low"
