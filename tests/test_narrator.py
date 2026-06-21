"""
tests/test_narrator.py

Unit tests for the Groq narrator (src/narration/narrator.py).
All tests use mock_groq — no real API calls.
"""

import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

os.environ.setdefault("GROQ_API_KEY", "test-key")

import pytest

from src.models import Risk
from src.narration.narrator import narrate_risk, narrate_risks, _fallback_narration


def _make_risk(narration: str = "") -> Risk:
    return Risk(
        id=str(uuid.uuid4()),
        signal_id=str(uuid.uuid4()),
        business_impact="Programme delivery milestone at critical risk.",
        confidence_band="high",
        priority="critical",
        suggested_owner_role="Programme-Manager",
        suggested_action="Convene emergency programme review.",
        root_cause_hypothesis="Resource constraint and dependency bottleneck.",
        supporting_document_ids=[str(uuid.uuid4())],
        narration=narration,
        created_at=datetime.utcnow(),
    )


class TestNarrateRisk:
    def test_narration_populated_from_groq(self, mock_groq):
        risk = _make_risk()
        result = narrate_risk(risk)
        assert result.narration
        assert len(result.narration) > 10

    def test_skips_already_narrated_risk(self, mock_groq):
        risk = _make_risk(narration="Already written.")
        result = narrate_risk(risk)
        # Should not call Groq again
        assert result.narration == "Already written."
        mock_groq.chat.completions.create.assert_not_called()

    def test_fallback_used_when_groq_fails(self):
        risk = _make_risk()
        with patch("src.narration.narrator._get_client") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = Exception("API error")
            result = narrate_risk(risk)
        # Fallback narration should be used — pipeline should not crash
        assert result.narration
        assert "milestone" in result.narration.lower() or "action" in result.narration.lower()

    def test_returns_same_risk_object(self, mock_groq):
        risk = _make_risk()
        result = narrate_risk(risk)
        assert result is risk  # same object, mutated in place

    def test_signal_title_used_in_prompt(self, mock_groq):
        risk = _make_risk()
        narrate_risk(risk, signal_title="Deployment pipeline failures")
        call_args = mock_groq.chat.completions.create.call_args
        prompt = call_args.kwargs["messages"][1]["content"]
        assert "Deployment pipeline failures" in prompt


class TestFallbackNarration:
    def test_fallback_contains_business_impact(self):
        risk = _make_risk()
        fallback = _fallback_narration(risk)
        assert "milestone at critical risk" in fallback

    def test_fallback_contains_suggested_action(self):
        risk = _make_risk()
        fallback = _fallback_narration(risk)
        assert "Convene emergency" in fallback

    def test_fallback_is_nonempty(self):
        risk = _make_risk()
        assert _fallback_narration(risk).strip()


class TestNarrateRisks:
    def test_narrates_all_risks(self, mock_groq):
        risks = [_make_risk() for _ in range(3)]
        results = narrate_risks(risks)
        assert all(r.narration for r in results)
        assert len(results) == 3

    def test_empty_list_returns_empty(self, mock_groq):
        result = narrate_risks([])
        assert result == []

    def test_uses_signal_titles_dict(self, mock_groq):
        risk = _make_risk()
        titles = {risk.signal_id: "Custom Signal Title"}
        narrate_risks([risk], signal_titles=titles)
        call_args = mock_groq.chat.completions.create.call_args
        prompt = call_args.kwargs["messages"][1]["content"]
        assert "Custom Signal Title" in prompt

    def test_continues_despite_individual_failure(self):
        risks = [_make_risk() for _ in range(3)]
        call_count = 0

        def flaky_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise Exception("flaky API")
            mock_response = MagicMock()
            mock_response.choices[0].message.content = "Good narration."
            return mock_response

        with patch("src.narration.narrator._get_client") as mock_client:
            mock_client.return_value.chat.completions.create.side_effect = flaky_create
            results = narrate_risks(risks)

        # All 3 should have narration (2 from Groq, 1 fallback)
        assert all(r.narration for r in results)
