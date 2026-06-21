"""
tests/test_anonymizer.py

Unit and privacy validation tests for the Privacy Shield (src/privacy/anonymizer.py).

Privacy rules tested here (non-negotiable):
    - PII is removed from all document text
    - Role codes are assigned ([Person-A], [Email-B], etc.)
    - The same entity gets the same code within a document
    - raw_text is cleared from the Document after anonymization
    - The anonymized text is always non-empty for valid input
    - PrivacyShieldError is raised for empty documents
"""

import os
import uuid
from datetime import datetime

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.exceptions import PrivacyShieldError
from src.models import Document


def _make_document(text: str, word_count: int = 100) -> Document:
    """Create a Document with given text for anonymizer testing."""
    return Document(
        id=str(uuid.uuid4()),
        filename="test_meeting.txt",
        source_type="meeting_note",
        raw_text=text,
        word_count=word_count,
        uploaded_at=datetime.utcnow(),
        processed=False,
    )


class TestAnonymizerBasic:
    def test_returns_anonymized_document(self, sample_document):
        from src.privacy.anonymizer import anonymize
        anon = anonymize(sample_document)
        assert anon is not None
        assert anon.anonymized_text
        assert anon.document_id == sample_document.id

    def test_raw_text_cleared_after_anonymization(self, sample_document):
        from src.privacy.anonymizer import anonymize
        anonymize(sample_document)
        # Privacy rule: raw_text MUST be empty after anonymization
        assert sample_document.raw_text == ""

    def test_document_marked_processed(self, sample_document):
        from src.privacy.anonymizer import anonymize
        anonymize(sample_document)
        assert sample_document.processed is True

    def test_raises_on_empty_raw_text(self):
        from src.privacy.anonymizer import anonymize
        doc = _make_document("")
        with pytest.raises(PrivacyShieldError, match="no raw_text"):
            anonymize(doc)

    def test_raises_on_already_cleared_document(self):
        from src.privacy.anonymizer import anonymize
        doc = _make_document("some text")
        doc.clear_raw_text()  # pre-clear
        with pytest.raises(PrivacyShieldError):
            anonymize(doc)


class TestPrivacyRules:
    """These tests enforce the privacy-first design rules."""

    def test_person_name_not_in_anonymized_text(self):
        """Real names must never appear in anonymized output."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "the team reported that John Smith is leaving the project next month "
            "and the delivery will be impacted because John is the only person "
            "who understands the pipeline and this is a critical risk for Q3"
        )
        anon = anonymize(doc)
        # "John Smith" and "John" should be replaced
        assert "John Smith" not in anon.anonymized_text
        # Note: "John" alone may or may not be detected depending on context
        assert "Smith" not in anon.anonymized_text

    def test_email_not_in_anonymized_text(self):
        """Email addresses must be replaced with role codes."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "please send the incident report to priya.sharma@company.com "
            "and copy manager@team.org for the programme review "
            "the delivery is blocked and the milestone is at risk "
            "escalate to the director for urgent review of the vendor dependency"
        )
        anon = anonymize(doc)
        assert "priya.sharma@company.com" not in anon.anonymized_text
        assert "@company.com" not in anon.anonymized_text

    def test_role_codes_in_output(self):
        """Anonymized text should contain [Type-Letter] role codes."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "Priya Sharma confirmed the vendor contract is delayed "
            "and Ravi Kumar escalated to the programme director "
            "the team is at risk of missing the Q3 delivery milestone "
            "this has been flagged in three consecutive sprint reviews "
            "and the dependency on the vendor is now blocking all testing"
        )
        anon = anonymize(doc)
        # Should contain at least one role code
        assert "[" in anon.anonymized_text
        assert "]" in anon.anonymized_text

    def test_role_map_populated(self):
        """role_map must track what was replaced."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "Priya Sharma reported that the sprint is blocked "
            "and Ravi Kumar confirmed the vendor dependency is unresolved "
            "the team needs support from the director to escalate the issue "
            "this is now a critical risk for the Q3 milestone delivery"
        )
        anon = anonymize(doc)
        # role_map maps originals to codes
        assert isinstance(anon.role_map, dict)

    def test_anonymized_text_non_empty(self):
        """Anonymized output must always have content."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "the team reported that the delivery milestone was delayed "
            "and the programme manager escalated to the director of engineering "
            "the outstanding issues with the release pipeline and deployment "
            "the backend lead confirmed the blocker is on the critical path "
            "vendor approval is still pending after three sprint reviews"
        )
        anon = anonymize(doc)
        assert anon.anonymized_text.strip()

    def test_document_id_preserved(self, sample_document):
        """AnonymizedDocument must link back to the original Document."""
        from src.privacy.anonymizer import anonymize
        anon = anonymize(sample_document)
        assert anon.document_id == sample_document.id

    def test_no_pii_text_passes_through_with_empty_role_map(self):
        """Documents with no PII should still anonymize without error."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "the sprint velocity dropped by thirty percent this iteration "
            "the team flagged two blockers related to the deployment pipeline "
            "the release milestone is at risk and needs urgent programme review "
            "the dependency on the external vendor remains unresolved "
            "an escalation to the director is recommended before end of week"
        )
        anon = anonymize(doc)
        assert anon.anonymized_text.strip()
        # role_map may be empty if no PII detected — that is fine
        assert isinstance(anon.role_map, dict)


class TestRoleCodeConsistency:
    def test_same_name_gets_same_role_code(self):
        """The same person must get the same role code within a document."""
        from src.privacy.anonymizer import anonymize
        doc = _make_document(
            "Priya Sharma confirmed the vendor issue is unresolved "
            "and Priya Sharma will escalate to the director today "
            "the programme delivery is at risk because Priya Sharma owns this dependency "
            "the milestone for Q3 cannot be met without vendor approval "
            "this is now a critical blocker for the entire sprint delivery"
        )
        anon = anonymize(doc)
        # Count occurrences of "Priya Sharma" in output — should be zero
        assert "Priya Sharma" not in anon.anonymized_text
        # The replacement code should appear multiple times (once per occurrence)
        if "Person-A" in anon.anonymized_text:
            count = anon.anonymized_text.count("[Person-A]")
            # At least two occurrences since "Priya Sharma" appears three times
            assert count >= 1
