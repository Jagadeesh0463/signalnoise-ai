"""
src/signals/aggregator.py

Signal Aggregator — merges semantically equivalent signals into canonical risks.

After BERTopic produces N raw topics, this module:
    1. Groups signals by canonical category
    2. Merges evidence and source documents across all signals in a group
    3. Takes the highest severity from the group
    4. Returns at most one Signal per canonical business risk

Problem solved:
    Without aggregation, three BERTopic topics for Auth API, Student Records API,
    and Vendor API all become separate "Dependency" cards. With aggregation they
    merge into one "Critical External Dependency Risk" with combined evidence.

Design rules:
    - NOISE signals are dropped before aggregation
    - Title comes from the highest-severity signal in each group
    - Evidence is deduplicated across merged signals (capped at 8 snippets)
    - Source document IDs are unioned across all merged signals

Usage:
    from src.signals.aggregator import aggregate_signals
    canonical = aggregate_signals(raw_signals)
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.models import Signal

logger = logging.getLogger(__name__)

# Severity ordering — higher is better
_SEVERITY_RANK = {"NOISE": 0, "WEAK": 1, "STRONG": 2}

# Confidence ordering
_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def aggregate_signals(signals: list[Signal]) -> list[Signal]:
    """
    Merge raw BERTopic signals by canonical category.

    Multiple signals in the same category are merged into one, combining
    their evidence and source documents. The merged signal takes the title,
    severity, and confidence of the strongest signal in the group.

    Args:
        signals: Raw Signal objects from detect_signals().

    Returns:
        Deduplicated list — at most one Signal per category.
        NOISE signals are excluded from the output.
    """
    actionable = [s for s in signals if s.severity != "NOISE"]

    if not actionable:
        logger.info("Aggregator: no actionable signals to process.")
        return []

    # Group by category
    groups: dict[str, list[Signal]] = {}
    for sig in actionable:
        groups.setdefault(sig.category, []).append(sig)

    merged: list[Signal] = []

    for category, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            logger.debug("Category '%s': single signal, no merge needed.", category)
            continue

        # Sort strongest first (severity desc, then confidence desc)
        group.sort(
            key=lambda s: (
                _SEVERITY_RANK.get(s.severity, 0),
                _CONFIDENCE_RANK.get(s.confidence_band, 0),
            ),
            reverse=True,
        )

        primary = group[0]  # use title, severity, confidence, owner from strongest

        # Merge evidence (deduplicate by normalised first 60 chars, cap at 8)
        seen: set[str] = set()
        merged_evidence: list[str] = []
        for sig in group:
            for ev in sig.evidence:
                key = ev.strip().lower()[:60]
                if key not in seen:
                    seen.add(key)
                    merged_evidence.append(ev)
                if len(merged_evidence) >= 8:
                    break
            if len(merged_evidence) >= 8:
                break

        # Union of all source document IDs
        all_doc_ids = list({
            doc_id
            for sig in group
            for doc_id in sig.source_document_ids
        })

        # Union of related teams and projects
        all_teams = list({t for sig in group for t in (sig.related_teams or [])})
        all_projects = list({p for sig in group for p in (sig.related_projects or [])})

        merged_signal = Signal(
            id=primary.id,
            title=primary.title,
            category=category,
            severity=primary.severity,
            confidence_band=primary.confidence_band,
            trend=primary.trend,
            evidence=merged_evidence,
            source_document_ids=all_doc_ids,
            suggested_owner_role=primary.suggested_owner_role,
            related_teams=all_teams,
            related_projects=all_projects,
            status="active",
            created_at=primary.created_at,
            updated_at=datetime.utcnow(),
        )

        logger.info(
            "Merged %d '%s' signals → '%s' [%s] | evidence=%d snippets | docs=%d",
            len(group),
            category,
            merged_signal.title,
            merged_signal.severity,
            len(merged_signal.evidence),
            len(all_doc_ids),
        )

        merged.append(merged_signal)

    logger.info(
        "Aggregation complete: %d actionable signals → %d canonical signals.",
        len(actionable),
        len(merged),
    )

    return merged
