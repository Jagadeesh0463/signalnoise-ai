"""
src/signals/detector.py

Signal Detector — uses BERTopic to cluster anonymized documents and
classify each cluster as NOISE, WEAK, or STRONG.

Pipeline position:
    Embedder (ChromaDB) → Detector → Evidence Validator

Classification rules:
    NOISE  — topic with < 2 documents OR topic content is generic/irrelevant
    WEAK   — topic with 2–3 documents OR low keyword signal strength
    STRONG — topic with 4+ documents AND strong risk keywords present

Design rules:
    - Input is always anonymized text — no PII reaches this module
    - NOISE signals are logged but never passed downstream
    - Minimum 10 documents required for reliable BERTopic clustering

Usage:
    from src.signals.detector import detect_signals
    signals = detect_signals(documents, embeddings, metadatas)
"""

import logging
import re
import uuid
from datetime import datetime

import numpy as np
from bertopic import BERTopic
from sklearn.feature_extraction.text import CountVectorizer

from src.config import config
from src.exceptions import DetectionError
from src.models import Signal

logger = logging.getLogger(__name__)

# ── Role code cleanup ─────────────────────────────────────────────────────────
# Presidio replaces PII with codes like [Person-A], [Date-B], [Location-C].
# These create junk tokens ("persona", "datea") in BERTopic's CountVectorizer.
# Strip them before topic modeling — ChromaDB retains the originals.

_ROLE_CODE_RE = re.compile(r'\[[A-Za-z]+-[A-Z0-9]+\]')


def _clean_for_topic_model(text: str) -> str:
    """Remove anonymization role codes so BERTopic sees only risk vocabulary."""
    return _ROLE_CODE_RE.sub(' ', text)

# ── Risk keyword vocabulary ───────────────────────────────────────────────────
# These words boost a topic's signal strength classification.
# All matched against anonymized text — no PII involved.

RISK_KEYWORDS = {
    # Delivery risk
    "delayed", "delay", "blocked", "blocking", "overdue", "slipped",
    "missed", "behind", "critical", "escalate", "escalation", "risk",
    "blocker", "dependency", "deadline", "milestone", "pushed", "deferred",

    # Team health
    "burnout", "understaffed", "capacity", "overwhelmed", "attrition",
    "leaving", "resigned", "morale", "frustrated", "unclear", "confusion",

    # Operational
    "incident", "outage", "failure", "failing", "degraded", "alert",
    "rollback", "hotfix", "breach", "error", "crash", "broken",

    # Process breakdown
    "unclear", "no owner", "unresolved", "pending", "waiting", "stuck",
    "no update", "no response", "ignored", "dropped", "forgotten",
}


# ── Classification thresholds ─────────────────────────────────────────────────

STRONG_MIN_DOCS = 4       # topic must have >= 4 documents
STRONG_MIN_KEYWORDS = 2   # topic must match >= 2 risk keywords
WEAK_MIN_DOCS = 2         # topic must have >= 2 documents


# ── Public API ────────────────────────────────────────────────────────────────

def detect_signals(
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> list[Signal]:
    """
    Run BERTopic on embedded documents and return classified signals.

    Args:
        documents:  List of anonymized text strings (from ChromaDB).
        embeddings: Corresponding 384-dim vectors.
        metadatas:  Metadata dicts from ChromaDB (contains document_id).

    Returns:
        List of Signal objects. NOISE signals are included with severity="NOISE"
        so they can be logged — filter them with signal.is_actionable() before
        passing to the Evidence Validator.

    Raises:
        DetectionError: If BERTopic fails or document count is too low.
    """
    if len(documents) < config.MIN_DOCS_FOR_BERTOPIC:
        raise DetectionError(
            f"Only {len(documents)} documents in ChromaDB. "
            f"Minimum required for reliable clustering: {config.MIN_DOCS_FOR_BERTOPIC}. "
            f"Upload more documents and try again."
        )

    logger.info("Running BERTopic on %d documents...", len(documents))

    # Strip role codes ([Person-A], [Date-B] etc.) before topic modeling.
    # Embeddings already computed from full anonymized text — this only
    # affects what keywords BERTopic extracts for signal titles.
    clean_docs = [_clean_for_topic_model(doc) for doc in documents]

    try:
        topic_model = _build_topic_model()
        embeddings_array = np.array(embeddings)

        # Fit BERTopic — uses pre-computed embeddings (no re-embedding)
        topics, probs = topic_model.fit_transform(clean_docs, embeddings_array)

        topic_info = topic_model.get_topic_info()
        logger.info("BERTopic found %d topics (including noise topic -1).", len(topic_info))

    except DetectionError:
        raise
    except Exception as exc:
        raise DetectionError(f"BERTopic clustering failed: {exc}") from exc

    # Group documents by topic
    topic_docs: dict[int, list[dict]] = {}
    for idx, topic_id in enumerate(topics):
        topic_id = int(topic_id)   # ensure Python int, not numpy.int64
        if topic_id not in topic_docs:
            topic_docs[topic_id] = []

        # Compute prob safely regardless of probs shape
        prob_val = 0.0
        if probs is not None:
            try:
                p = probs[idx]
                # p might be a numpy scalar OR a 1-D array — handle both
                prob_val = float(p) if np.ndim(p) == 0 else float(np.max(p))
            except Exception:
                prob_val = 0.0

        topic_docs[topic_id].append({
            "text": documents[idx],
            "metadata": metadatas[idx] if idx < len(metadatas) else {},
            "prob": prob_val,
        })

    signals: list[Signal] = []

    for topic_id, doc_group in topic_docs.items():
        signal = _build_signal(topic_id, doc_group, topic_model)
        signals.append(signal)
        logger.info(
            "Topic %d → Signal '%s' [%s] — %d documents",
            topic_id,
            signal.title[:50],
            signal.severity,
            len(doc_group),
        )

    actionable = sum(1 for s in signals if s.is_actionable())
    logger.info(
        "Detection complete — %d signals total, %d actionable (WEAK/STRONG).",
        len(signals),
        actionable,
    )

    return signals


# ── Internal helpers ──────────────────────────────────────────────────────────

def _build_topic_model() -> BERTopic:
    """
    Build a BERTopic model configured for MVP scale (10–100 documents).
    Uses a simple CountVectorizer — no additional NLP models required.
    """
    vectorizer = CountVectorizer(
        stop_words="english",
        min_df=1,               # include rare terms at MVP scale
        ngram_range=(1, 2),     # unigrams and bigrams
    )

    model = BERTopic(
        vectorizer_model=vectorizer,
        min_topic_size=config.MIN_TOPIC_SIZE,
        nr_topics=None,         # no auto-reduction — fails on small datasets
        calculate_probabilities=False,  # probs array causes numpy bool errors on edge cases
        verbose=False,
    )
    return model


def _classify_severity(topic_id: int, doc_count: int, top_words: list[str]) -> str:
    """
    Classify a topic as NOISE, WEAK, or STRONG.

    Rules:
        NOISE  — BERTopic outlier topic (-1) OR fewer than WEAK_MIN_DOCS documents
        STRONG — >= STRONG_MIN_DOCS documents AND >= STRONG_MIN_KEYWORDS risk keywords
        WEAK   — everything else that passes the minimum doc threshold
    """
    # BERTopic assigns topic_id = -1 to outlier / unclustered documents
    if topic_id == -1:
        return "NOISE"

    if doc_count < WEAK_MIN_DOCS:
        return "NOISE"

    # Count risk keyword matches in topic's top words
    top_words_lower = {w.lower() for w in top_words}
    keyword_hits = top_words_lower & RISK_KEYWORDS

    if doc_count >= STRONG_MIN_DOCS and len(keyword_hits) >= STRONG_MIN_KEYWORDS:
        return "STRONG"

    return "WEAK"


def _classify_confidence(severity: str, doc_count: int) -> str:
    """
    Return a confidence band (low / medium / high).
    Never expose raw probability scores to users — PRD §8.
    """
    if severity == "NOISE":
        return "low"
    if severity == "STRONG" and doc_count >= 6:
        return "high"
    if severity == "STRONG":
        return "medium"
    return "low"   # WEAK signals


def _infer_category(top_words: list[str]) -> str:
    """
    Infer signal category from BERTopic's top keywords.
    Returns one of: delivery_risk | team_health | operational | dependency
    """
    words = {w.lower() for w in top_words}

    operational_words = {"incident", "outage", "failure", "alert", "rollback", "hotfix", "crash"}
    team_words = {"burnout", "capacity", "morale", "attrition", "understaffed", "leaving"}
    dependency_words = {"blocked", "blocking", "dependency", "waiting", "vendor", "approval"}

    if words & operational_words:
        return "operational"
    if words & team_words:
        return "team_health"
    if words & dependency_words:
        return "dependency"
    return "delivery_risk"   # default — most common in MVP context


def _make_title(category: str, top_words: list[str]) -> str:
    """
    Generate a human-readable signal title from category and BERTopic keywords.

    Avoids raw keyword dumps like "Signal: data, team, pipeline".
    Instead produces phrases like "Deployment Pipeline Instability" that
    a Program Manager can understand without ML knowledge.

    Args:
        category:  Inferred category (delivery_risk, team_health, etc.)
        top_words: BERTopic's top keywords for the topic.

    Returns:
        A readable title string.
    """
    words = {w.lower() for w in top_words}

    # ── Delivery risk titles ──────────────────────────────────────────────────
    if category == "delivery_risk":
        if words & {"sprint", "velocity", "missed", "slipped"}:
            return "Repeated Sprint Velocity Decline"
        if words & {"milestone", "deadline", "deadline", "pushed", "deferred"}:
            return "Delivery Milestone at Risk"
        if words & {"pipeline", "deployment", "release", "deploy"}:
            return "Deployment Pipeline Instability"
        if words & {"auth", "api", "service", "integration"}:
            return "API Integration Delivery Risk"
        return "Delivery Risk Detected"

    # ── Team health titles ────────────────────────────────────────────────────
    if category == "team_health":
        if words & {"burnout", "overtime", "weekend", "exhausted"}:
            return "Team Burnout Risk"
        if words & {"leaving", "attrition", "resigned", "quit"}:
            return "Attrition and Retention Risk"
        if words & {"morale", "frustrated", "disengaged", "unhappy"}:
            return "Low Team Morale"
        if words & {"capacity", "understaffed", "overloaded", "bandwidth"}:
            return "Team Capacity Overload"
        return "Team Health Concern"

    # ── Operational titles ────────────────────────────────────────────────────
    if category == "operational":
        if words & {"incident", "outage", "crash", "down"}:
            return "Production Incident or Outage"
        if words & {"pipeline", "data", "sync", "job"}:
            return "Data Pipeline Failure"
        if words & {"bug", "bugs", "production", "hotfix"}:
            return "Production Bugs Slipping Through QA"
        if words & {"alert", "monitor", "metric", "threshold"}:
            return "Operational Alert Threshold Breached"
        return "Operational Risk Detected"

    # ── Dependency titles ─────────────────────────────────────────────────────
    if category == "dependency":
        if words & {"auth", "api", "authentication", "login"}:
            return "Auth API Dependency Blocker"
        if words & {"vendor", "external", "third", "supplier"}:
            return "External Vendor Dependency Blocked"
        if words & {"blocked", "blocking", "waiting", "unresolved"}:
            return "Critical Dependency Unresolved"
        return "Dependency Blocker Identified"

    return "Organizational Risk Signal"


def _build_signal(
    topic_id: int,
    doc_group: list[dict],
    topic_model: BERTopic,
) -> Signal:
    """
    Build a Signal object from a BERTopic topic and its documents.
    """
    doc_count = len(doc_group)

    # Get BERTopic's top words for this topic
    if topic_id != -1:
        try:
            topic_words = topic_model.get_topic(topic_id)
            top_words = [word for word, _ in topic_words[:10]] if topic_words else []
        except Exception:
            top_words = []
    else:
        top_words = []

    severity = _classify_severity(topic_id, doc_count, top_words)
    confidence_band = _classify_confidence(severity, doc_count)
    category = _infer_category(top_words)

    # Title: human-readable phrase from category + keywords
    title = _make_title(category, top_words)

    # Evidence: take the highest-probability snippets (first 150 chars each)
    sorted_docs = sorted(doc_group, key=lambda d: d["prob"], reverse=True)
    evidence = [d["text"][:150].strip() for d in sorted_docs[:3]]

    # Source document IDs from metadata
    source_doc_ids = [
        d["metadata"].get("document_id", "unknown")
        for d in doc_group
    ]

    # Suggested owner by category — diversified per reviewer feedback
    owner_map = {
        "delivery_risk": "Program-Manager",
        "team_health":   "Engineering-Manager",
        "operational":   "SRE-Lead",
        "dependency":    "Platform-Lead",
    }

    return Signal(
        id=str(uuid.uuid4()),
        title=title,
        category=category,
        severity=severity,
        confidence_band=confidence_band,
        trend="emerging",           # default; updated by memory store over time
        evidence=evidence,
        source_document_ids=source_doc_ids,
        suggested_owner_role=owner_map.get(category, "Program-Manager"),
        related_teams=[],           # populated by knowledge graph in Sprint 2
        related_projects=[],        # populated by knowledge graph in Sprint 2
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
