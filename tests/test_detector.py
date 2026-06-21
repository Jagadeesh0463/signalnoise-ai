"""
tests/test_detector.py

Unit tests for the signal detector (src/signals/detector.py).
Tests classification logic and role code cleanup — not BERTopic itself
(BERTopic integration tested in tests/test_integration.py).
"""

import os
import uuid

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.signals.detector import (
    RISK_KEYWORDS,
    _classify_severity,
    _classify_confidence,
    _infer_category,
    _clean_for_topic_model,
)


class TestClassifySeverity:
    def test_topic_minus_one_is_noise(self):
        assert _classify_severity(-1, 10, ["risk", "blocked"]) == "NOISE"

    def test_single_doc_is_noise(self):
        assert _classify_severity(0, 1, ["risk", "blocked"]) == "NOISE"

    def test_two_docs_no_keywords_is_weak(self):
        assert _classify_severity(0, 2, ["meeting", "update"]) == "WEAK"

    def test_four_docs_two_keywords_is_strong(self):
        assert _classify_severity(0, 4, ["delayed", "blocked", "sprint"]) == "STRONG"

    def test_four_docs_one_keyword_is_weak(self):
        # 4 docs but only 1 risk keyword — not strong enough
        assert _classify_severity(0, 4, ["delayed", "sprint", "update"]) == "WEAK"

    def test_three_docs_two_keywords_is_weak(self):
        # < STRONG_MIN_DOCS (4) — even with keywords
        assert _classify_severity(0, 3, ["delayed", "blocked"]) == "WEAK"

    def test_strong_requires_both_thresholds(self):
        # Exactly at thresholds
        result = _classify_severity(0, 4, ["delayed", "blocked"])
        assert result == "STRONG"


class TestClassifyConfidence:
    def test_noise_is_low(self):
        assert _classify_confidence("NOISE", 10) == "low"

    def test_weak_is_low(self):
        assert _classify_confidence("WEAK", 5) == "low"

    def test_strong_with_few_docs_is_medium(self):
        assert _classify_confidence("STRONG", 4) == "medium"

    def test_strong_with_many_docs_is_high(self):
        assert _classify_confidence("STRONG", 6) == "high"

    def test_strong_exactly_six_is_high(self):
        assert _classify_confidence("STRONG", 6) == "high"

    def test_strong_five_is_medium(self):
        assert _classify_confidence("STRONG", 5) == "medium"


class TestInferCategory:
    def test_incident_words_give_operational(self):
        assert _infer_category(["incident", "outage", "rollback"]) == "operational"

    def test_burnout_words_give_team_health(self):
        assert _infer_category(["burnout", "capacity", "morale"]) == "team_health"

    def test_vendor_words_give_dependency(self):
        assert _infer_category(["blocked", "vendor", "waiting"]) == "dependency"

    def test_generic_words_give_delivery_risk(self):
        assert _infer_category(["sprint", "milestone", "delayed"]) == "delivery_risk"

    def test_empty_words_give_delivery_risk(self):
        assert _infer_category([]) == "delivery_risk"

    def test_operational_takes_priority_over_others(self):
        # Both operational and team health words present
        assert _infer_category(["incident", "burnout"]) == "operational"


class TestCleanForTopicModel:
    def test_removes_person_codes(self):
        text = "[Person-A] reported the issue."
        result = _clean_for_topic_model(text)
        assert "[Person-A]" not in result
        assert "reported the issue" in result

    def test_removes_date_codes(self):
        text = "Meeting on [Date-A] was cancelled."
        result = _clean_for_topic_model(text)
        assert "[Date-A]" not in result

    def test_removes_location_codes(self):
        text = "The team in [Location-B] is blocked."
        result = _clean_for_topic_model(text)
        assert "[Location-B]" not in result

    def test_removes_multiple_codes(self):
        text = "[Person-A] and [Person-B] discussed [Date-A] risks at [Location-C]."
        result = _clean_for_topic_model(text)
        assert "[" not in result or "]" not in result

    def test_preserves_risk_vocabulary(self):
        text = "[Person-A] escalated the blocked vendor dependency."
        result = _clean_for_topic_model(text)
        assert "escalated" in result
        assert "blocked" in result
        assert "vendor" in result
        assert "dependency" in result

    def test_empty_string_unchanged(self):
        assert _clean_for_topic_model("") == ""

    def test_no_codes_unchanged(self):
        text = "Normal text without any role codes."
        assert _clean_for_topic_model(text) == text


class TestRiskKeywords:
    def test_risk_keywords_is_nonempty_set(self):
        assert isinstance(RISK_KEYWORDS, set)
        assert len(RISK_KEYWORDS) > 10

    def test_key_risk_terms_present(self):
        for term in ["blocked", "burnout", "incident", "delayed", "attrition"]:
            assert term in RISK_KEYWORDS

    def test_all_keywords_are_lowercase(self):
        for keyword in RISK_KEYWORDS:
            assert keyword == keyword.lower(), f"Keyword '{keyword}' is not lowercase"
