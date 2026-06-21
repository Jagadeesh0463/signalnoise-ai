"""
tests/test_models.py

Unit tests for shared data models (src/models.py).
"""

import os
import uuid
from datetime import datetime

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.models import (
    AnonymizedDocument,
    Document,
    Evidence,
    Feedback,
    Risk,
    Signal,
    _new_id,
)


class TestNewId:
    def test_returns_string(self):
        assert isinstance(_new_id(), str)

    def test_is_valid_uuid(self):
        uid = _new_id()
        # Should not raise
        uuid.UUID(uid)

    def test_unique_each_call(self):
        ids = {_new_id() for _ in range(100)}
        assert len(ids) == 100


class TestDocument:
    def test_default_id_assigned(self):
        doc = Document(
            filename="test.txt",
            source_type="meeting_note",
            raw_text="some text",
            word_count=2,
        )
        assert doc.id
        uuid.UUID(doc.id)  # valid UUID

    def test_default_not_processed(self):
        doc = Document(
            filename="test.txt",
            source_type="meeting_note",
            raw_text="some text",
            word_count=2,
        )
        assert doc.processed is False

    def test_clear_raw_text(self):
        doc = Document(
            filename="test.txt",
            source_type="meeting_note",
            raw_text="sensitive PII here",
            word_count=4,
        )
        doc.clear_raw_text()
        assert doc.raw_text == ""
        assert doc.processed is True

    def test_uploaded_at_defaults_to_now(self):
        before = datetime.utcnow()
        doc = Document(
            filename="test.txt",
            source_type="meeting_note",
            raw_text="text",
            word_count=1,
        )
        after = datetime.utcnow()
        assert before <= doc.uploaded_at <= after


class TestAnonymizedDocument:
    def test_fields_set_correctly(self):
        anon = AnonymizedDocument(
            document_id="abc-123",
            anonymized_text="[Person-A] reported an issue.",
            role_map={"John": "Person-A"},
        )
        assert anon.document_id == "abc-123"
        assert "[Person-A]" in anon.anonymized_text
        assert anon.role_map["John"] == "Person-A"

    def test_auto_id(self):
        anon = AnonymizedDocument(
            document_id="abc",
            anonymized_text="text",
            role_map={},
        )
        assert anon.id
        uuid.UUID(anon.id)


class TestSignal:
    def test_is_actionable_strong(self, sample_signal):
        assert sample_signal.is_actionable() is True

    def test_is_actionable_weak(self, sample_weak_signal):
        assert sample_weak_signal.is_actionable() is True

    def test_noise_not_actionable(self):
        signal = Signal(
            title="noise",
            category="delivery_risk",
            severity="NOISE",
            confidence_band="low",
            trend="emerging",
            evidence=[],
            source_document_ids=[],
            suggested_owner_role="Programme-Manager",
            related_teams=[],
            related_projects=[],
        )
        assert signal.is_actionable() is False

    def test_default_status_active(self, sample_signal):
        assert sample_signal.status == "active"

    def test_default_id_assigned(self, sample_signal):
        uuid.UUID(sample_signal.id)


class TestEvidence:
    def test_evidence_links_to_signal(self, sample_evidence, sample_signal):
        assert sample_evidence.signal_id == sample_signal.id

    def test_default_source_count(self):
        ev = Evidence(
            signal_id="sig-1",
            document_id="doc-1",
            snippet="some text",
            relevance_score=0.8,
        )
        assert ev.source_count == 1


class TestRisk:
    def test_risk_links_to_signal(self, sample_risk, sample_signal):
        assert sample_risk.signal_id == sample_signal.id

    def test_narration_empty_by_default(self, sample_risk):
        assert sample_risk.narration == ""

    def test_priority_is_set(self, sample_risk):
        assert sample_risk.priority in ("critical", "high", "medium", "low")


class TestFeedback:
    def test_feedback_decision_values(self):
        for decision in ("confirmed", "dismissed"):
            fb = Feedback(
                signal_id="sig-1",
                reviewer_role="Programme-Manager",
                decision=decision,
            )
            assert fb.decision == decision

    def test_comment_optional(self):
        fb = Feedback(
            signal_id="sig-1",
            reviewer_role="Director",
            decision="confirmed",
        )
        assert fb.comment is None
