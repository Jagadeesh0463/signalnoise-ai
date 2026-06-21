"""
tests/test_aggregator.py

Tests for src/signals/aggregator.py
"""

from datetime import datetime

import pytest

from src.models import Signal
from src.signals.aggregator import aggregate_signals


def _make_signal(
    category: str,
    severity: str = "STRONG",
    confidence_band: str = "high",
    title: str = "",
    evidence: list[str] | None = None,
    source_doc_ids: list[str] | None = None,
) -> Signal:
    return Signal(
        id=f"test-{category}-{severity}",
        title=title or f"{category.title()} Risk",
        category=category,
        severity=severity,
        confidence_band=confidence_band,
        trend="emerging",
        evidence=evidence or ["snippet one", "snippet two"],
        source_document_ids=source_doc_ids or ["doc-1"],
        suggested_owner_role="Program-Manager",
        related_teams=[],
        related_projects=[],
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


class TestAggregateSignals:
    def test_empty_input_returns_empty(self):
        assert aggregate_signals([]) == []

    def test_noise_signals_are_dropped(self):
        noise = _make_signal("delivery_risk", severity="NOISE")
        result = aggregate_signals([noise])
        assert result == []

    def test_single_signal_passes_through_unchanged(self):
        sig = _make_signal("delivery_risk")
        result = aggregate_signals([sig])
        assert len(result) == 1
        assert result[0].id == sig.id
        assert result[0].category == "delivery_risk"

    def test_two_signals_same_category_merge_into_one(self):
        s1 = _make_signal("dependency", severity="STRONG", title="Auth API Blocker",
                           source_doc_ids=["doc-1", "doc-2"])
        s2 = _make_signal("dependency", severity="WEAK", title="Vendor API Blocked",
                           source_doc_ids=["doc-3"])
        result = aggregate_signals([s1, s2])
        assert len(result) == 1
        merged = result[0]
        assert merged.category == "dependency"
        # Primary title comes from strongest signal
        assert merged.title == "Auth API Blocker"
        # Severity takes the strongest
        assert merged.severity == "STRONG"

    def test_merged_signal_combines_source_documents(self):
        s1 = _make_signal("dependency", source_doc_ids=["doc-1", "doc-2"])
        s2 = _make_signal("dependency", source_doc_ids=["doc-3"])
        result = aggregate_signals([s1, s2])
        assert set(result[0].source_document_ids) == {"doc-1", "doc-2", "doc-3"}

    def test_merged_signal_combines_evidence_deduplicated(self):
        s1 = _make_signal("dependency", evidence=["waiting three weeks", "auth api blocked"])
        s2 = _make_signal("dependency", evidence=["auth api blocked", "vendor timeout"])  # duplicate
        result = aggregate_signals([s1, s2])
        # "auth api blocked" appears in both — deduplicated
        ev = result[0].evidence
        counts = sum(1 for e in ev if "auth api blocked" in e.lower())
        assert counts == 1

    def test_different_categories_produce_separate_signals(self):
        dep = _make_signal("dependency")
        burnout = _make_signal("team_health")
        result = aggregate_signals([dep, burnout])
        assert len(result) == 2
        categories = {s.category for s in result}
        assert categories == {"dependency", "team_health"}

    def test_three_dependency_signals_merge_to_one(self):
        s1 = _make_signal("dependency", title="Auth API Dependency Blocker",
                           source_doc_ids=["doc-1"])
        s2 = _make_signal("dependency", title="Student Records API Dependency Risk",
                           source_doc_ids=["doc-2"])
        s3 = _make_signal("dependency", title="Vendor API Blocked",
                           source_doc_ids=["doc-3"])
        result = aggregate_signals([s1, s2, s3])
        assert len(result) == 1
        assert len(result[0].source_document_ids) == 3

    def test_evidence_capped_at_eight_snippets(self):
        # 3 signals with 4 unique snippets each → 12 total, capped at 8
        signals = []
        for i in range(3):
            ev = [f"unique snippet {i}-{j}" for j in range(4)]
            signals.append(_make_signal("delivery_risk", evidence=ev, source_doc_ids=[f"doc-{i}"]))
        result = aggregate_signals(signals)
        assert len(result[0].evidence) <= 8

    def test_noise_mixed_with_actionable_drops_noise(self):
        noise = _make_signal("delivery_risk", severity="NOISE")
        strong = _make_signal("team_health", severity="STRONG")
        result = aggregate_signals([noise, strong])
        assert len(result) == 1
        assert result[0].severity == "STRONG"

    def test_highest_confidence_band_preserved_in_merge(self):
        low = _make_signal("dependency", severity="WEAK", confidence_band="low")
        high = _make_signal("dependency", severity="STRONG", confidence_band="high")
        result = aggregate_signals([low, high])
        assert result[0].confidence_band == "high"
