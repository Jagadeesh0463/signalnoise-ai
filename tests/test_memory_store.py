"""
tests/test_memory_store.py

Unit tests for the SQLite memory store (src/memory/store.py).
"""

import os
import uuid
from datetime import datetime

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.models import Document, Evidence, Feedback, Signal


class TestSaveAndRetrieveSignal:
    def test_save_and_get_active_signals(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        signals = memory_store.get_active_signals()
        assert len(signals) == 1
        assert signals[0]["id"] == sample_signal.id
        assert signals[0]["severity"] == "STRONG"

    def test_get_signal_by_id(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        retrieved = memory_store.get_signal(sample_signal.id)
        assert retrieved is not None
        assert retrieved["title"] == sample_signal.title

    def test_get_signal_nonexistent_returns_none(self, memory_store):
        result = memory_store.get_signal("does-not-exist")
        assert result is None

    def test_multiple_signals_ordered_newest_first(self, memory_store, sample_signal, sample_weak_signal):
        memory_store.save_signal(sample_signal)
        memory_store.save_signal(sample_weak_signal)
        signals = memory_store.get_active_signals()
        assert len(signals) == 2
        # Newest first — weak_signal was saved last
        assert signals[0]["id"] == sample_weak_signal.id

    def test_save_signal_writes_history(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        history = memory_store.get_signal_history(sample_signal.id)
        assert len(history) == 1
        assert history[0]["severity"] == "STRONG"

    def test_noise_signal_saved_but_active(self, memory_store):
        noise_signal = Signal(
            title="Unclustered signal",
            category="delivery_risk",
            severity="NOISE",
            confidence_band="low",
            trend="emerging",
            evidence=[],
            source_document_ids=[],
            suggested_owner_role="Programme-Manager",
            related_teams=[],
            related_projects=[],
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        memory_store.save_signal(noise_signal)
        # NOISE signals are still stored (for logging) and returned by get_active_signals
        signals = memory_store.get_active_signals()
        assert any(s["id"] == noise_signal.id for s in signals)


class TestFeedback:
    def test_save_feedback_updates_signal_status(self, memory_store, sample_signal, sample_feedback):
        memory_store.save_signal(sample_signal)
        memory_store.save_feedback(sample_feedback)

        retrieved = memory_store.get_signal(sample_signal.id)
        assert retrieved["status"] == "confirmed"

    def test_dismissed_feedback_sets_status(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        fb = Feedback(
            id=str(uuid.uuid4()),
            signal_id=sample_signal.id,
            reviewer_role="Director",
            decision="dismissed",
            created_at=datetime.utcnow(),
        )
        memory_store.save_feedback(fb)

        retrieved = memory_store.get_signal(sample_signal.id)
        assert retrieved["status"] == "dismissed"

    def test_get_feedback_for_signal(self, memory_store, sample_signal, sample_feedback):
        memory_store.save_signal(sample_signal)
        memory_store.save_feedback(sample_feedback)
        feedbacks = memory_store.get_feedback_for_signal(sample_signal.id)
        assert len(feedbacks) == 1
        assert feedbacks[0]["decision"] == "confirmed"

    def test_dismissed_signals_not_in_active(self, memory_store, sample_signal, sample_feedback):
        memory_store.save_signal(sample_signal)
        # Dismiss the signal
        fb = Feedback(
            id=str(uuid.uuid4()),
            signal_id=sample_signal.id,
            reviewer_role="Director",
            decision="dismissed",
            created_at=datetime.utcnow(),
        )
        memory_store.save_feedback(fb)
        # get_active_signals returns status='active' only
        active = memory_store.get_active_signals()
        assert not any(s["id"] == sample_signal.id for s in active)


class TestEvidence:
    def test_save_and_retrieve_evidence(self, memory_store, sample_signal, sample_evidence):
        memory_store.save_signal(sample_signal)
        memory_store.save_evidence(sample_evidence)
        evidence = memory_store.get_evidence_for_signal(sample_signal.id)
        assert len(evidence) == 1
        assert evidence[0]["snippet"] == sample_evidence.snippet

    def test_evidence_ordered_by_relevance(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        for score in [0.5, 0.9, 0.3]:
            ev = Evidence(
                id=str(uuid.uuid4()),
                signal_id=sample_signal.id,
                document_id=str(uuid.uuid4()),
                snippet=f"evidence with score {score}",
                relevance_score=score,
                source_count=1,
            )
            memory_store.save_evidence(ev)
        evidence = memory_store.get_evidence_for_signal(sample_signal.id)
        scores = [e["relevance_score"] for e in evidence]
        assert scores == sorted(scores, reverse=True)

    def test_no_evidence_returns_empty_list(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        result = memory_store.get_evidence_for_signal(sample_signal.id)
        assert result == []


class TestDocument:
    def test_save_and_get_document(self, memory_store, sample_document):
        memory_store.save_document(sample_document)
        retrieved = memory_store.get_document(sample_document.id)
        assert retrieved is not None
        assert retrieved["filename"] == sample_document.filename

    def test_mark_document_processed(self, memory_store, sample_document):
        memory_store.save_document(sample_document)
        memory_store.mark_document_processed(sample_document.id)
        retrieved = memory_store.get_document(sample_document.id)
        assert retrieved["processed"] == 1
        assert retrieved["deleted"] == 1


class TestAuditLog:
    def test_signal_save_creates_audit_entry(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        logs = memory_store.get_audit_log()
        actions = [log["action"] for log in logs]
        assert "signal_detected" in actions

    def test_feedback_creates_audit_entry(self, memory_store, sample_signal, sample_feedback):
        memory_store.save_signal(sample_signal)
        memory_store.save_feedback(sample_feedback)
        logs = memory_store.get_audit_log()
        actions = [log["action"] for log in logs]
        assert "feedback_given" in actions

    def test_audit_log_respects_limit(self, memory_store, sample_signal):
        for _ in range(10):
            sig = Signal(
                title="test signal",
                category="delivery_risk",
                severity="WEAK",
                confidence_band="low",
                trend="emerging",
                evidence=[],
                source_document_ids=[],
                suggested_owner_role="Programme-Manager",
                related_teams=[],
                related_projects=[],
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            memory_store.save_signal(sig)
        logs = memory_store.get_audit_log(limit=5)
        assert len(logs) <= 5


class TestDigest:
    def test_get_top_signals_strong_first(self, memory_store, sample_signal, sample_weak_signal):
        memory_store.save_signal(sample_weak_signal)
        memory_store.save_signal(sample_signal)
        top = memory_store.get_top_signals_for_digest(limit=3)
        assert top[0]["severity"] == "STRONG"

    def test_digest_excludes_dismissed(self, memory_store, sample_signal):
        memory_store.save_signal(sample_signal)
        fb = Feedback(
            id=str(uuid.uuid4()),
            signal_id=sample_signal.id,
            reviewer_role="Director",
            decision="dismissed",
            created_at=datetime.utcnow(),
        )
        memory_store.save_feedback(fb)
        top = memory_store.get_top_signals_for_digest()
        assert not any(s["id"] == sample_signal.id for s in top)
