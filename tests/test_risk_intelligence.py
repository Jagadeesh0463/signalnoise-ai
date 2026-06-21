"""
tests/test_risk_intelligence.py

Unit tests for Risk Intelligence (src/risk/intelligence.py).
"""

import os
import uuid
from datetime import datetime

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.evidence.validator import ValidationResult
from src.exceptions import RiskIntelligenceError
from src.models import Evidence, Signal
from src.risk.intelligence import (
    PRIORITY_MAP,
    build_risk,
    build_risks,
    _get_priority,
    _get_business_impact,
    _get_suggested_action,
    _get_root_cause,
)


def _make_validation_result(
    severity: str = "STRONG",
    confidence_band: str = "high",
    category: str = "delivery_risk",
    passed: bool = True,
) -> ValidationResult:
    signal = Signal(
        id=str(uuid.uuid4()),
        title="Test signal",
        category=category,
        severity=severity,
        confidence_band=confidence_band,
        trend="emerging",
        evidence=["evidence text"],
        source_document_ids=[str(uuid.uuid4()), str(uuid.uuid4())],
        suggested_owner_role="Programme-Manager",
        related_teams=[],
        related_projects=[],
        status="active",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    evidence_list = [
        Evidence(
            id=str(uuid.uuid4()),
            signal_id=signal.id,
            document_id=str(uuid.uuid4()),
            snippet="test evidence",
            relevance_score=0.9,
        )
    ]
    return ValidationResult(
        signal=signal,
        passed=passed,
        evidence_list=evidence_list,
        reason="" if passed else "insufficient evidence",
    )


class TestBuildRisk:
    def test_build_risk_from_strong_signal(self):
        vr = _make_validation_result(severity="STRONG", confidence_band="high")
        risk = build_risk(vr)
        assert risk.priority == "critical"
        assert risk.signal_id == vr.signal.id
        assert risk.narration == ""  # narrator fills this

    def test_build_risk_fails_on_failed_validation(self):
        vr = _make_validation_result(passed=False)
        with pytest.raises(RiskIntelligenceError, match="failed validation"):
            build_risk(vr)

    def test_build_risk_fails_on_noise_signal(self):
        vr = _make_validation_result(severity="NOISE")
        vr.signal.severity = "NOISE"
        with pytest.raises(RiskIntelligenceError, match="NOISE"):
            build_risk(vr)

    def test_supporting_doc_ids_deduped(self):
        vr = _make_validation_result()
        # Two evidence items pointing to the same document
        doc_id = str(uuid.uuid4())
        vr.evidence_list = [
            Evidence(
                id=str(uuid.uuid4()),
                signal_id=vr.signal.id,
                document_id=doc_id,
                snippet="a",
                relevance_score=0.9,
            ),
            Evidence(
                id=str(uuid.uuid4()),
                signal_id=vr.signal.id,
                document_id=doc_id,  # same doc
                snippet="b",
                relevance_score=0.8,
            ),
        ]
        risk = build_risk(vr)
        assert len(risk.supporting_document_ids) == 1


class TestPriorityMapping:
    def test_strong_high_is_critical(self):
        vr = _make_validation_result(severity="STRONG", confidence_band="high")
        assert _get_priority(vr.signal) == "critical"

    def test_strong_medium_is_high(self):
        vr = _make_validation_result(severity="STRONG", confidence_band="medium")
        assert _get_priority(vr.signal) == "high"

    def test_weak_high_is_medium(self):
        vr = _make_validation_result(severity="WEAK", confidence_band="high")
        assert _get_priority(vr.signal) == "medium"

    def test_weak_low_is_low(self):
        vr = _make_validation_result(severity="WEAK", confidence_band="low")
        assert _get_priority(vr.signal) == "low"

    def test_unknown_combination_defaults_to_low(self):
        vr = _make_validation_result(severity="WEAK", confidence_band="unknown")
        # PRIORITY_MAP has no entry for this — should default to "low"
        assert _get_priority(vr.signal) == "low"


class TestCategoryTemplates:
    @pytest.mark.parametrize("category", ["delivery_risk", "team_health", "operational", "dependency"])
    def test_all_categories_have_impact(self, category):
        vr = _make_validation_result(category=category)
        impact = _get_business_impact(vr.signal, "critical")
        assert impact
        assert len(impact) > 10

    @pytest.mark.parametrize("category", ["delivery_risk", "team_health", "operational", "dependency"])
    def test_all_categories_have_action(self, category):
        vr = _make_validation_result(category=category)
        action = _get_suggested_action(vr.signal, "critical")
        assert action
        assert len(action) > 10

    @pytest.mark.parametrize("category", ["delivery_risk", "team_health", "operational", "dependency"])
    def test_all_categories_have_root_cause(self, category):
        vr = _make_validation_result(category=category)
        cause = _get_root_cause(vr.signal)
        assert cause
        assert len(cause) > 10

    def test_unknown_category_falls_back_to_delivery_risk(self):
        vr = _make_validation_result(category="unknown_category")
        impact = _get_business_impact(vr.signal, "critical")
        # Should not raise — falls back to delivery_risk template
        assert impact


class TestBuildRisks:
    def test_build_risks_batch(self):
        vrs = [_make_validation_result() for _ in range(3)]
        risks = build_risks(vrs)
        assert len(risks) == 3

    def test_build_risks_skips_failed(self):
        vrs = [
            _make_validation_result(passed=True),
            _make_validation_result(passed=False),
            _make_validation_result(passed=True),
        ]
        risks = build_risks(vrs)
        assert len(risks) == 2

    def test_build_risks_empty_list(self):
        risks = build_risks([])
        assert risks == []
