"""
tests/test_confidence.py

Tests for src/signals/confidence.py
"""

from datetime import datetime

import pytest

from src.models import Evidence, Signal
from src.signals.confidence import band_from_score, compute_confidence


def _make_signal(
    category: str = "delivery_risk",
    severity: str = "STRONG",
    confidence_band: str = "high",
    evidence: list[str] | None = None,
    source_doc_ids: list[str] | None = None,
) -> Signal:
    return Signal(
        id="test-sig-01",
        title="Test Signal",
        category=category,
        severity=severity,
        confidence_band=confidence_band,
        trend="emerging",
        evidence=evidence or [],
        source_document_ids=source_doc_ids or [],
        suggested_owner_role="Program-Manager",
        related_teams=[],
        related_projects=[],
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )


def _make_evidence(signal_id: str, snippet: str, relevance: float = 0.8) -> Evidence:
    return Evidence(
        id="test-ev-01",
        signal_id=signal_id,
        document_id="doc-1",
        snippet=snippet,
        relevance_score=relevance,
        source_count=1,
    )


class TestComputeConfidence:
    def test_returns_tuple_of_int_and_dict(self):
        sig = _make_signal()
        score, breakdown = compute_confidence(sig)
        assert isinstance(score, int)
        assert isinstance(breakdown, dict)

    def test_score_within_valid_range(self):
        sig = _make_signal()
        score, _ = compute_confidence(sig)
        assert 50 <= score <= 97

    def test_strong_signal_scores_higher_than_weak(self):
        strong = _make_signal(severity="STRONG", source_doc_ids=["d1", "d2", "d3", "d4"])
        weak = _make_signal(severity="WEAK", source_doc_ids=["d1"])
        strong_score, _ = compute_confidence(strong, total_docs=10)
        weak_score, _ = compute_confidence(weak, total_docs=10)
        assert strong_score > weak_score

    def test_more_documents_increases_confidence(self):
        few_docs = _make_signal(source_doc_ids=["d1"])
        many_docs = _make_signal(source_doc_ids=[f"d{i}" for i in range(6)])
        score_few, _ = compute_confidence(few_docs, total_docs=10)
        score_many, _ = compute_confidence(many_docs, total_docs=10)
        assert score_many > score_few

    def test_evidence_list_increases_confidence(self):
        sig = _make_signal()
        ev_list = [_make_evidence("test-sig-01", f"snippet {i}") for i in range(5)]
        score_no_ev, _ = compute_confidence(sig, evidence_list=[])
        score_with_ev, _ = compute_confidence(sig, evidence_list=ev_list)
        assert score_with_ev > score_no_ev

    def test_breakdown_contains_all_components(self):
        sig = _make_signal()
        _, breakdown = compute_confidence(sig)
        expected_keys = {
            "doc_coverage", "evidence_quality", "severity_weight",
            "keyword_density", "category_prior", "weighted_sum",
        }
        assert expected_keys.issubset(set(breakdown.keys()))

    def test_breakdown_values_between_zero_and_one(self):
        sig = _make_signal()
        _, breakdown = compute_confidence(sig)
        for key, val in breakdown.items():
            if key != "weighted_sum":
                assert 0.0 <= val <= 1.0, f"{key} = {val} out of range"

    def test_dependency_category_has_higher_prior_than_delivery(self):
        dep = _make_signal(category="dependency", severity="STRONG",
                           source_doc_ids=["d1", "d2"])
        delivery = _make_signal(category="delivery_risk", severity="STRONG",
                                source_doc_ids=["d1", "d2"])
        dep_score, _ = compute_confidence(dep)
        del_score, _ = compute_confidence(delivery)
        assert dep_score >= del_score

    def test_keyword_rich_evidence_increases_score(self):
        sig = _make_signal(evidence=["blocked blocked blocked delayed missed sprint"])
        plain_sig = _make_signal(evidence=["the team met and discussed progress"])
        score_rich, _ = compute_confidence(sig)
        score_plain, _ = compute_confidence(plain_sig)
        assert score_rich > score_plain

    def test_noise_signal_returns_low_score(self):
        noise = _make_signal(severity="NOISE", confidence_band="low")
        score, _ = compute_confidence(noise)
        assert score <= 65


class TestBandFromScore:
    def test_high_band(self):
        assert band_from_score(90) == "high"
        assert band_from_score(85) == "high"

    def test_medium_band(self):
        assert band_from_score(80) == "medium"
        assert band_from_score(65) == "medium"

    def test_low_band(self):
        assert band_from_score(64) == "low"
        assert band_from_score(50) == "low"
